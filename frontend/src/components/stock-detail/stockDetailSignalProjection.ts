import {
  finiteNumber,
  formatPct,
  formatSignedLots,
  formatSignedNumber,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  TechnicalReport,
  TechnicalReportRow,
  TechnicalTone,
} from "@/components/stock-detail/StockDetailDataViews";
import type { TranslationFunction } from "@/i18n";
import type {
  InstitutionalTradeDailyRead,
  MarginTradingDailyRead,
  MonthlyRevenueRead,
  OvernightImpactRead,
} from "@/types/market";

export type StockSignalTone = "positive" | "negative" | "warning" | "neutral";

export type StockSignalChip = {
  key: string;
  source: string;
  label: string;
  tone: StockSignalTone;
  title?: string;
};

function stockSignalToneFromNumber(value: number | null | undefined): StockSignalTone {
  if (!finiteNumber(value)) return "neutral";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

function stockSignalToneFromTechnical(tone: TechnicalTone | undefined): StockSignalTone {
  if (tone === "positive" || tone === "negative" || tone === "warning") return tone;
  return "neutral";
}

function addStockSignalChip(
  chips: StockSignalChip[],
  chip: StockSignalChip | null
) {
  if (!chip || !chip.label || chips.some((item) => item.key === chip.key)) return;
  chips.push(chip);
}

function findTechnicalRow(report: TechnicalReport, title: string) {
  return report.rows.find((row) => row.title.includes(title)) ?? null;
}

function findTechnicalRowByKey(report: TechnicalReport, key: string) {
  return report.rows.find((row) => row.key === key) ?? null;
}

function findTechnicalBadge(report: TechnicalReport, patterns: string[]) {
  return (
    report.badges.find((badge) =>
      patterns.some((pattern) => badge.label.includes(pattern))
    ) ?? null
  );
}

function stockSignalToneFromBadgeLabel(label: string): StockSignalTone {
  const normalized = label.toLowerCase();
  if (
    label.includes("過熱") ||
    label.includes("放量") ||
    label.includes("高位") ||
    normalized.includes("overheated") ||
    normalized.includes("surge") ||
    normalized.includes("high")
  ) {
    return "warning";
  }

  if (
    label.includes("跌破") ||
    label.includes("偏弱") ||
    label.includes("衰退") ||
    label.includes("減少") ||
    normalized.includes("below") ||
    normalized.includes("weak") ||
    normalized.includes("decline") ||
    normalized.includes("decrease")
  ) {
    return "negative";
  }

  if (
    label.includes("站上") ||
    label.includes("偏多") ||
    label.includes("成長") ||
    label.includes("增加") ||
    label.includes("走升") ||
    normalized.includes("above") ||
    normalized.includes("bullish") ||
    normalized.includes("growth") ||
    normalized.includes("increase") ||
    normalized.includes("rising")
  ) {
    return "positive";
  }

  return "neutral";
}

function usableTechnicalRowValue(row: TechnicalReportRow | null) {
  const value = row?.value?.trim();
  return value && value !== "-" ? value : null;
}

function signedTextTone(valueText: string | null): StockSignalTone {
  if (!valueText) return "neutral";
  if (valueText.trim().startsWith("+")) return "positive";
  if (valueText.trim().startsWith("-")) return "negative";
  return "neutral";
}

function signedLabelFromValue(valueText: string, positiveLabel: string, negativeLabel: string, neutralLabel: string) {
  if (valueText.trim().startsWith("+")) return positiveLabel;
  if (valueText.trim().startsWith("-")) return negativeLabel;
  return neutralLabel;
}

export function stockTechnicalText(
  t: TranslationFunction,
  key: string,
  values?: Record<string, string | number | null | undefined>
) {
  return t(`stockDetail.dataViews.technical.${key}`, values);
}

export function stockTechnicalTerm(t: TranslationFunction, key: string) {
  return stockTechnicalText(t, `terms.${key}`);
}

function withLotsUnit(value: string, t: TranslationFunction) {
  if (value === "-") return value;
  return `${value}${t("stockDetail.dataPanel.units.lots")}`;
}

function formatSignedLotsWithUnit(value: number | null | undefined, t: TranslationFunction) {
  return withLotsUnit(formatSignedLots(value), t);
}

function extractSignedNumberAfter(text: string | null | undefined, keyword: string) {
  if (!text) return null;

  const index = text.indexOf(keyword);
  if (index < 0) return null;
  const tail = text.slice(index + keyword.length);
  const match = tail.match(/[+-]?\d[\d,]*(?:\.\d+)?/);
  if (!match) return null;

  const value = Number(match[0].replace(/,/g, ""));
  return Number.isFinite(value) ? value : null;
}

export function buildStockSignalChips({
  technicalReport,
  institutional,
  margin,
  monthlyRevenue,
  overnightImpact,
  relativeToPrimaryIndex,
  primaryMarketLabel,
  t,
}: {
  technicalReport: TechnicalReport;
  institutional: InstitutionalTradeDailyRead | null;
  margin: MarginTradingDailyRead | null;
  monthlyRevenue: MonthlyRevenueRead | null;
  overnightImpact: OvernightImpactRead | null;
  relativeToPrimaryIndex: number | null;
  primaryMarketLabel: string;
  t: TranslationFunction;
}) {
  const chips: StockSignalChip[] = [];
  const trendBadge = findTechnicalBadge(technicalReport, ["MA20", "Trend", "trend", "月線", "週線"]);
  const momentumBadge = findTechnicalBadge(technicalReport, ["MACD", "RSI", "Momentum", "動能"]);
  const volumeBadge = findTechnicalBadge(technicalReport, ["Volume", "volume", "放量", "量能"]);
  const trendRow =
    findTechnicalRowByKey(technicalReport, "trend_structure") ??
    findTechnicalRowByKey(technicalReport, "daily_background") ??
    findTechnicalRow(technicalReport, "趨勢") ??
    findTechnicalRow(technicalReport, "Trend") ??
    findTechnicalRow(technicalReport, "Background");
  const momentumRow =
    findTechnicalRowByKey(technicalReport, "momentum") ??
    findTechnicalRow(technicalReport, "動能") ??
    findTechnicalRow(technicalReport, "Momentum");
  const volumeRow =
    findTechnicalRowByKey(technicalReport, "volume_flow") ??
    findTechnicalRowByKey(technicalReport, "volume_pace") ??
    findTechnicalRow(technicalReport, "量價") ??
    findTechnicalRow(technicalReport, "量能") ??
    findTechnicalRow(technicalReport, "Volume");
  const institutionalRow =
    findTechnicalRowByKey(technicalReport, "institutional_flow") ??
    findTechnicalRow(technicalReport, "法人") ??
    findTechnicalRow(technicalReport, "Institutional");
  const institutionalRowValue = usableTechnicalRowValue(institutionalRow);
  const rowMarginBalanceChange = extractSignedNumberAfter(
    institutionalRow?.description,
    "融資餘額"
  ) ?? extractSignedNumberAfter(institutionalRow?.description, "margin balance");
  const marginTodayBalance = margin?.margin_today_balance ?? null;
  const marginPreviousBalance = margin?.margin_previous_balance ?? null;
  const marginBalanceChange =
    finiteNumber(marginTodayBalance) && finiteNumber(marginPreviousBalance)
      ? marginTodayBalance - marginPreviousBalance
      : rowMarginBalanceChange;
  const institutionalNet = institutional?.total_institutional_net ?? null;
  const revenueGrowth = monthlyRevenue?.year_over_year_pct ?? null;
  const overnightChange = overnightImpact?.weighted_change_pct ?? null;

  addStockSignalChip(chips, {
    key: "classification",
    source: stockTechnicalText(t, "chips.sources.classification"),
    label: technicalReport.title,
    tone: stockSignalToneFromNumber(technicalReport.value),
    title: technicalReport.summary,
  });

  addStockSignalChip(chips, {
    key: "trend",
    source: stockTechnicalText(t, "chips.sources.trend"),
    label:
      trendBadge?.label ??
      (trendRow?.value && trendRow.value !== "-" ? `${trendRow.title} ${trendRow.value}` : ""),
    tone: trendBadge
      ? stockSignalToneFromBadgeLabel(trendBadge.label)
      : stockSignalToneFromTechnical(trendRow?.tone),
    title: trendRow?.description,
  });

  addStockSignalChip(chips, {
    key: "momentum",
    source: stockTechnicalText(t, "chips.sources.momentum"),
    label:
      momentumBadge?.label ??
      (momentumRow?.direction !== null && momentumRow?.direction !== undefined
        ? momentumRow.direction >= 0
          ? stockTechnicalTerm(t, "macdBullish")
          : stockTechnicalTerm(t, "macdWeak")
        : ""),
    tone: momentumBadge
      ? stockSignalToneFromBadgeLabel(momentumBadge.label)
      : stockSignalToneFromTechnical(momentumRow?.tone),
    title: momentumRow?.description,
  });

  addStockSignalChip(chips, {
    key: "volume",
    source: stockTechnicalText(t, "chips.sources.volume"),
    label:
      volumeBadge?.label ??
      (volumeRow?.value && volumeRow.value !== "-"
        ? stockTechnicalText(t, "chips.volumeValue", { value: volumeRow.value })
        : ""),
    tone: volumeBadge
      ? stockSignalToneFromBadgeLabel(volumeBadge.label)
      : stockSignalToneFromTechnical(volumeRow?.tone),
    title: volumeRow?.description,
  });

  if (finiteNumber(institutionalNet) || institutionalRowValue) {
    addStockSignalChip(chips, {
      key: "institutional",
      source: stockTechnicalText(t, "chips.sources.chip"),
      label: finiteNumber(institutionalNet)
        ? `${
            institutionalNet > 0
              ? stockTechnicalTerm(t, "institutionalBuy")
              : institutionalNet < 0
                ? stockTechnicalTerm(t, "institutionalSell")
                : stockTechnicalTerm(t, "institutionalFlat")
          } ${formatSignedLotsWithUnit(institutionalNet, t)}`
        : `${signedLabelFromValue(
            institutionalRowValue ?? "",
            stockTechnicalTerm(t, "institutionalBuy"),
            stockTechnicalTerm(t, "institutionalSell"),
            stockTechnicalTerm(t, "institutionalFlat")
          )} ${institutionalRowValue}`,
      tone: finiteNumber(institutionalNet)
        ? stockSignalToneFromNumber(institutionalNet)
        : signedTextTone(institutionalRowValue),
      title: finiteNumber(institutionalNet)
        ? stockTechnicalText(t, "chips.latestInstitutionalTotal", {
            value: formatSignedLotsWithUnit(institutionalNet, t),
          })
        : institutionalRow?.description,
    });
  }

  if (finiteNumber(marginBalanceChange)) {
    addStockSignalChip(chips, {
      key: "margin",
      source: stockTechnicalText(t, "chips.sources.margin"),
      label:
        marginBalanceChange > 0
          ? stockTechnicalText(t, "chips.marginIncrease", {
              value: formatSignedNumber(marginBalanceChange),
            })
          : marginBalanceChange < 0
            ? stockTechnicalText(t, "chips.marginDecrease", {
                value: formatSignedNumber(marginBalanceChange),
              })
            : stockTechnicalTerm(t, "marginFlat"),
      tone: marginBalanceChange > 0 ? "warning" : stockSignalToneFromNumber(-marginBalanceChange),
      title: stockTechnicalText(t, "chips.marginBalanceChange", {
        value: formatSignedNumber(marginBalanceChange),
      }),
    });
  }

  if (finiteNumber(revenueGrowth)) {
    addStockSignalChip(chips, {
      key: "revenue",
      source: stockTechnicalText(t, "chips.sources.revenue"),
      label:
        revenueGrowth > 0
          ? stockTechnicalText(t, "chips.revenueGrowth", { value: formatPct(revenueGrowth) })
          : revenueGrowth < 0
            ? stockTechnicalText(t, "chips.revenueDecline", { value: formatPct(revenueGrowth) })
            : stockTechnicalTerm(t, "revenueFlat"),
      tone: stockSignalToneFromNumber(revenueGrowth),
      title: stockTechnicalText(t, "chips.monthlyRevenueYoy", {
        value: formatPct(revenueGrowth),
      }),
    });
  }

  if (finiteNumber(overnightChange)) {
    addStockSignalChip(chips, {
      key: "overnight",
      source: stockTechnicalText(t, "chips.sources.overnight"),
      label:
        overnightChange > 0
          ? stockTechnicalText(t, "chips.usBullish", { value: formatPct(overnightChange) })
          : overnightChange < 0
            ? stockTechnicalText(t, "chips.usBearish", { value: formatPct(overnightChange) })
            : stockTechnicalTerm(t, "overnightNeutral"),
      tone: stockSignalToneFromNumber(overnightChange),
      title: stockTechnicalText(t, "chips.overnightImpact", {
        label: stockTechnicalTerm(t, "usOvernightMapping"),
        value: formatPct(overnightChange),
      }),
    });
  }

  if (finiteNumber(relativeToPrimaryIndex)) {
    addStockSignalChip(chips, {
      key: "market-relative",
      source: stockTechnicalText(t, "chips.sources.market"),
      label:
        relativeToPrimaryIndex > 0
          ? stockTechnicalText(t, "chips.strongerThanMarket", {
              value: formatPct(relativeToPrimaryIndex),
            })
          : relativeToPrimaryIndex < 0
            ? stockTechnicalText(t, "chips.weakerThanMarket", {
                value: formatPct(relativeToPrimaryIndex),
              })
            : stockTechnicalTerm(t, "marketInLine"),
      tone: stockSignalToneFromNumber(relativeToPrimaryIndex),
      title: stockTechnicalText(t, "chips.relativeToMarket", {
        market: primaryMarketLabel,
        value: formatPct(relativeToPrimaryIndex),
      }),
    });
  }

  return chips;
}

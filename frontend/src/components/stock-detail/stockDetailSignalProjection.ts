import {
  finiteNumber,
  formatPct,
  formatSignedLots,
  formatSignedNumber,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  DataPanelTab,
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
export type StockSignalGroup = "technical" | "context";
export const STOCK_DETAIL_DATA_PANEL_ID = "tw-stock-detail-data-panel";

export type StockSignalChip = {
  key: string;
  group: StockSignalGroup;
  source: string;
  label: string;
  tone: StockSignalTone;
  title?: string;
  horizon?: string;
  asOf?: string | null;
  detailTarget?: string;
  dataTabTarget?: DataPanelTab;
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

function formatPercentagePoints(value: number | null | undefined) {
  const formatted = formatPct(value);
  return formatted === "-" ? formatted : formatted.replace(/%$/, "pp");
}

function currentStatePositionLabel(
  report: TechnicalReport,
  t: TranslationFunction
) {
  const position = report.currentState?.position;
  if (!position || position.availableCount <= 0) {
    return stockTechnicalTerm(t, "insufficientStructure");
  }
  if (position.belowCount > 0) {
    return stockTechnicalText(t, "chips.belowAverages", {
      count: position.belowCount,
      total: position.availableCount,
    });
  }
  return stockTechnicalText(t, "chips.aboveAverages", {
    count: position.aboveCount,
    total: position.availableCount,
  });
}

function overnightStanceTone(
  stance: string,
  confidence: string
): StockSignalTone {
  if (confidence === "low") return "neutral";
  if (stance === "strong_risk_on" || stance === "risk_on") return "positive";
  if (stance === "strong_risk_off" || stance === "risk_off") return "negative";
  return "neutral";
}

function overnightStanceLabel(stance: string, t: TranslationFunction) {
  const key =
    stance === "strong_risk_on"
      ? "overnightStrongRiskOn"
      : stance === "risk_on"
        ? "overnightRiskOn"
        : stance === "strong_risk_off"
          ? "overnightStrongRiskOff"
          : stance === "risk_off"
            ? "overnightRiskOff"
            : stance === "neutral"
              ? "overnightNeutral"
              : "insufficient";
  return stockTechnicalTerm(t, key);
}

function detailWithAsOf(
  detail: string,
  asOf: string | null | undefined,
  t: TranslationFunction
) {
  if (!asOf) return detail;
  return stockTechnicalText(t, "chips.detailWithAsOf", {
    detail,
    date: asOf.slice(0, 10),
  });
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
  const currentState = technicalReport.currentState;
  const currentEvidence = currentState
    ? Object.fromEntries(
        currentState.evidence.map((item) => [item.key, item])
      )
    : {};

  if (currentState) {
    const trendEvidence = currentEvidence.trend;
    const momentumEvidence = currentEvidence.momentum;
    const volumeEvidence = currentEvidence.volume;
    const riskEvidence = currentEvidence.risk;
    const riskLevel = currentState.levels.find(
      (level) => level.key === "support20"
    );

    addStockSignalChip(chips, {
      key: "structure",
      group: "technical",
      source: stockTechnicalText(t, "chips.sources.structure"),
      label: currentStatePositionLabel(technicalReport, t),
      tone: stockSignalToneFromTechnical(currentState.headline.tone),
      title: trendEvidence?.summary ?? technicalReport.summary,
      horizon: "daily",
      detailTarget: "tw-technical-evidence-trend",
    });
    addStockSignalChip(chips, {
      key: "momentum",
      group: "technical",
      source: stockTechnicalText(t, "chips.sources.momentum"),
      label: currentState.qualifier.label,
      tone: stockSignalToneFromTechnical(currentState.qualifier.tone),
      title: momentumEvidence?.summary,
      horizon: "daily",
      detailTarget: "tw-technical-evidence-momentum",
    });
    addStockSignalChip(chips, {
      key: "volume",
      group: "technical",
      source: stockTechnicalText(t, "chips.sources.volume"),
      label: volumeEvidence?.stateLabel ?? stockTechnicalTerm(t, "volumeInsufficient"),
      tone: stockSignalToneFromTechnical(volumeEvidence?.tone),
      title: volumeEvidence?.summary,
      horizon: "daily",
      detailTarget: "tw-technical-evidence-volume",
    });
    addStockSignalChip(chips, {
      key: "risk",
      group: "technical",
      source: stockTechnicalText(t, "chips.sources.risk"),
      label:
        riskLevel?.role === "risk" && finiteNumber(riskLevel.moveRequiredPct)
          ? stockTechnicalText(t, "chips.riskDistance", {
              value: formatPct(riskLevel.moveRequiredPct),
            })
          : riskLevel?.role === "broken_support"
            ? stockTechnicalTerm(t, "riskLineBroken")
            : riskEvidence?.stateLabel ?? stockTechnicalTerm(t, "signalInsufficient"),
      tone: stockSignalToneFromTechnical(riskEvidence?.tone),
      title: riskEvidence?.summary,
      horizon: "daily",
      detailTarget: "tw-technical-evidence-risk",
    });
  } else {
    addStockSignalChip(chips, {
      key: "trend",
      group: "technical",
      source: stockTechnicalText(t, "chips.sources.trend"),
      label:
        trendBadge?.label ??
        (trendRow?.value && trendRow.value !== "-"
          ? `${trendRow.title} ${trendRow.value}`
          : ""),
      tone: trendBadge
        ? stockSignalToneFromBadgeLabel(trendBadge.label)
        : stockSignalToneFromTechnical(trendRow?.tone),
      title: trendRow?.description,
    });

    addStockSignalChip(chips, {
      key: "momentum",
      group: "technical",
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
      group: "technical",
      source: stockTechnicalText(t, "chips.sources.volume"),
      label:
        volumeBadge?.label ??
        (volumeRow?.value && volumeRow.value !== "-"
          ? volumeRow.value
          : ""),
      tone: volumeBadge
        ? stockSignalToneFromBadgeLabel(volumeBadge.label)
        : stockSignalToneFromTechnical(volumeRow?.tone),
      title: volumeRow?.description,
    });
  }

  if (finiteNumber(institutionalNet) || institutionalRowValue) {
    addStockSignalChip(chips, {
      key: "institutional",
      group: "context",
      source: stockTechnicalText(t, "chips.sources.chip"),
      label: finiteNumber(institutionalNet)
        ? stockTechnicalText(t, "chips.oneDayValue", {
            value: formatSignedLotsWithUnit(institutionalNet, t),
          })
        : stockTechnicalText(t, "chips.oneDayValue", {
            value: institutionalRowValue,
          }),
      tone: finiteNumber(institutionalNet)
        ? stockSignalToneFromNumber(institutionalNet)
        : signedTextTone(institutionalRowValue),
      title: detailWithAsOf(
        finiteNumber(institutionalNet)
          ? stockTechnicalText(t, "chips.latestInstitutionalTotal", {
              value: formatSignedLotsWithUnit(institutionalNet, t),
            })
          : institutionalRow?.description ?? "",
        institutional?.trade_date,
        t
      ),
      horizon: "1d",
      asOf: institutional?.trade_date,
      detailTarget: STOCK_DETAIL_DATA_PANEL_ID,
      dataTabTarget: "institutional",
    });
  }

  if (finiteNumber(marginBalanceChange)) {
    addStockSignalChip(chips, {
      key: "margin",
      group: "context",
      source: stockTechnicalText(t, "chips.sources.margin"),
      label: stockTechnicalText(t, "chips.marginBalanceDelta", {
        value: formatSignedNumber(marginBalanceChange),
      }),
      tone: "neutral",
      title: detailWithAsOf(
        stockTechnicalText(t, "chips.marginBalanceChange", {
          value: formatSignedNumber(marginBalanceChange),
        }),
        margin?.trade_date,
        t
      ),
      horizon: "1d",
      asOf: margin?.trade_date,
      detailTarget: STOCK_DETAIL_DATA_PANEL_ID,
      dataTabTarget: "chips",
    });
  }

  if (finiteNumber(revenueGrowth)) {
    addStockSignalChip(chips, {
      key: "revenue",
      group: "context",
      source: stockTechnicalText(t, "chips.sources.revenue"),
      label: stockTechnicalText(t, "chips.revenueYoyValue", {
        value: formatPct(revenueGrowth),
      }),
      tone: stockSignalToneFromNumber(revenueGrowth),
      title: detailWithAsOf(
        stockTechnicalText(t, "chips.monthlyRevenueYoy", {
          value: formatPct(revenueGrowth),
        }),
        monthlyRevenue?.period,
        t
      ),
      horizon: "monthly_yoy",
      asOf: monthlyRevenue?.period,
      detailTarget: STOCK_DETAIL_DATA_PANEL_ID,
      dataTabTarget: "revenue",
    });
  }

  if (finiteNumber(overnightChange)) {
    addStockSignalChip(chips, {
      key: "overnight",
      group: "context",
      source: stockTechnicalText(t, "chips.sources.overnight"),
      label: stockTechnicalText(t, "chips.overnightStanceValue", {
        stance: overnightStanceLabel(overnightImpact?.stance ?? "unknown", t),
        value: formatPct(overnightChange),
      }),
      tone: overnightStanceTone(
        overnightImpact?.stance ?? "unknown",
        overnightImpact?.confidence ?? "low"
      ),
      title: overnightImpact?.summary,
      horizon: "overnight",
      asOf: overnightImpact?.as_of,
      detailTarget: "tw-technical-context",
    });
  }

  if (finiteNumber(relativeToPrimaryIndex)) {
    addStockSignalChip(chips, {
      key: "market-relative",
      group: "context",
      source: stockTechnicalText(t, "chips.sources.market"),
      label:
        relativeToPrimaryIndex > 0
          ? stockTechnicalText(t, "chips.aheadOfMarket", {
              value: formatPercentagePoints(relativeToPrimaryIndex),
            })
          : relativeToPrimaryIndex < 0
            ? stockTechnicalText(t, "chips.behindMarket", {
                value: formatPercentagePoints(relativeToPrimaryIndex),
              })
            : stockTechnicalText(t, "chips.inLineWithMarket", {
                value: formatPercentagePoints(relativeToPrimaryIndex),
              }),
      tone: stockSignalToneFromNumber(relativeToPrimaryIndex),
      title: stockTechnicalText(t, "chips.relativeToMarket", {
        market: primaryMarketLabel,
        value: formatPercentagePoints(relativeToPrimaryIndex),
      }),
      horizon: "session_relative",
      detailTarget: "tw-technical-context",
    });
  }

  return chips;
}

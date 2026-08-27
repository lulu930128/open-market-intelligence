"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import { StockDetailDisclosure } from "@/components/stock-detail/DataPanelPrimitives";
import {
  formatPct,
  formatPrice,
} from "@/components/stock-detail/stockDetailFormatters";
import { useT, type TranslationFunction, type TranslationValues } from "@/i18n";
import type { StockTechnicalReportRead } from "@/types/market";
import type { ReactNode } from "react";

export type TechnicalTone = "positive" | "negative" | "neutral" | "warning";

export type TechnicalReportRow = {
  key?: string;
  title: string;
  description: string;
  value: string;
  pulseValue?: number | string | null;
  direction?: number | null;
  tone?: TechnicalTone;
};

export type TechnicalReportBadge = {
  label: string;
  tone: string;
};

export type TechnicalCurrentStateLevel = {
  key: string;
  role: "risk" | "broken_support" | "reclaim" | "support" | "current" | "resistance" | string;
  label: string;
  price: number | null;
  moveRequiredPct: number | null;
  referenceDistancePct: number | null;
  tone: TechnicalTone;
};

export type TechnicalCurrentStateEvidence = {
  key: string;
  label: string;
  stateKey: string;
  stateLabel: string;
  tone: TechnicalTone;
  summary: string;
  metrics: Record<string, number | null>;
};

export type TechnicalCurrentStateCondition = {
  key: string;
  label: string;
  tone: TechnicalTone;
  levelKey: string | null;
  price: number | null;
};

export type TechnicalCurrentState = {
  version: string;
  headline: {
    key: string;
    label: string;
    tone: TechnicalTone;
  };
  qualifier: {
    key: string;
    label: string;
    tone: TechnicalTone;
  };
  summary: string;
  position: {
    price: number | null;
    label: string;
    belowCount: number;
    aboveCount: number;
    availableCount: number;
    order: string[];
    orderLabel: string;
    alignment: string;
    alignmentLabel: string;
    distancePct: Record<string, number | null>;
  };
  levels: TechnicalCurrentStateLevel[];
  evidence: TechnicalCurrentStateEvidence[];
  nextConditions: TechnicalCurrentStateCondition[];
};

export type TechnicalReport = {
  title: string;
  summary: string;
  value: number | null;
  valueLabel: string;
  score: number;
  rows: TechnicalReportRow[];
  badges: TechnicalReportBadge[];
  currentState?: TechnicalCurrentState | null;
  decisionState?: TechnicalCurrentState | null;
  decisionStateTime?: string | null;
  decisionStateStatus?: string | null;
  currentObservation?: {
    status: string | null;
    time: string | null;
    decisionUsable: boolean;
    officialDailyConfirmed: boolean;
    currentState: TechnicalCurrentState | null;
  } | null;
  currentStateStatus?: string | null;
  currentStateDecisionUsable?: boolean;
  basisLabel?: string | null;
  warningCount?: number;
};

function translatedValue(
  t: TranslationFunction | undefined,
  key: string,
  fallback: string,
  values?: TranslationValues
) {
  if (!t) return fallback;
  const translated = t(key, values);
  return translated === key ? fallback : translated;
}

const technicalTextKeyMap: Record<string, string> = {
  資料讀取中: "loading",
  資料不足: "insufficient",
  等待盤中資料: "waitingIntraday",
  開盤偏強: "openingStrong",
  開盤觀察: "openingWatch",
  開盤偏弱: "openingWeak",
  盤中偏多: "intradayBullish",
  盤中觀察: "intradayWatch",
  盤中偏弱: "intradayWeak",
  短線偏多: "dailyBullish",
  短線整理: "dailyNeutral",
  短線偏弱: "dailyWeak",
  波段偏多: "weeklyBullish",
  波段整理: "weeklyNeutral",
  波段偏弱: "weeklyWeak",
  中線轉強: "swingBullish",
  中線整理: "swingNeutral",
  中線偏弱: "swingWeak",
  長線偏多: "longBullish",
  長線整理: "longNeutral",
  長線觀察: "longWatch",
  長線偏弱: "longWeak",
  資料狀態: "dataStatus",
  參考基準: "referenceBase",
  即時價格: "livePrice",
  開盤結構: "openingStructure",
  量能速度: "volumePace",
  日線背景: "dailyBackground",
  法人籌碼: "institutionalFlow",
  相對市場: "relativeMarket",
  趨勢結構: "trendStructure",
  價格位置: "pricePosition",
  動能指標: "momentum",
  量價資金: "volumeFlow",
  波動風險: "volatilityRisk",
  中線趨勢: "swingTrend",
  區間位置: "rangePosition",
  週量節奏: "weeklyVolume",
  法人累積: "institutionalAccumulation",
  市場背景: "marketBackground",
  長線趨勢: "longTrend",
  長期區間: "longRange",
  營收動能: "revenueMomentum",
  獲利品質: "earningsQuality",
  長期籌碼: "longChipFlow",
  "站上 MA20": "aboveMa20",
  "跌破 MA20": "belowMa20",
  "站上 MA60": "aboveMa60",
  "失守 MA60": "belowMa60",
  "站上 MA5/MA20/MA60": "aboveAllMa",
  "失守 MA5/MA20/MA60": "belowAllMa",
  多頭排列: "bullishAlignment",
  空頭排列: "bearishAlignment",
  "均線糾結／轉換中": "mixedAlignment",
  均線排列資料不足: "alignmentInsufficient",
  "盤中價 × 已收盤指標": "provisionalDailyIndicators",
  盤中現價: "intradayPrice",
  收盤價: "closingPrice",
  "跌破 20 日支撐": "supportBreak",
  "突破 20 日壓力": "resistanceBreakout",
  "跌破 20 日低": "donchianBreakdown",
  "突破 20 日高": "donchianBreakout",
  跌破布林下緣: "bollingerBreakdown",
  突破布林上緣: "bollingerBreakout",
  "MACD 偏多": "macdBullish",
  "MACD 偏弱": "macdWeak",
  "RSI 過熱": "rsiOverheated",
  放量: "volumeSurge",
  走升: "rising",
  走弱: "weakening",
  等待盤中: "waitingIntradayShort",
  開盤資料少: "openingSparse",
  開高: "gapUp",
  開低: "gapDown",
  "日線站上 MA20": "dailyAboveMa20",
  "日線跌破 MA20": "dailyBelowMa20",
  "日線 RSI 過熱": "dailyRsiOverheated",
  週線偏多: "weeklyBullishLine",
  週線偏弱: "weeklyWeakLine",
  "接近26週高位": "near26WeekHigh",
  週量放大: "weeklyVolumeSurge",
  月線偏多: "monthlyBullishLine",
  月線偏弱: "monthlyWeakLine",
  營收成長: "revenueGrowth",
  營收衰退: "revenueDecline",
  大戶增加: "largeHoldersIncreasing",
  大戶減少: "largeHoldersDecreasing",
  籌碼待讀取: "chipFlowPending",
  營收待讀取: "revenuePending",
  法人累積買超: "institutionalAccumulationBuy",
  法人累積賣超: "institutionalAccumulationSell",
  位於區間上緣: "nearRangeHigh",
  位於區間下緣: "nearRangeLow",
  區間中段: "rangeMiddle",
  現價高於昨收: "priceAbovePreviousClose",
  現價低於昨收: "priceBelowPreviousClose",
  漲跌資料不足: "changeInsufficient",
  開盤資料不足: "openingInsufficient",
  日線指標僅作背景: "dailyIndicatorsAsBackground",
  盤中資料已進入觀察期: "intradayObservationReady",
  "接近12月高位": "near12MonthHigh",
  價格結構不足: "priceStructureInsufficient",
  動能資料不足: "momentumInsufficient",
  量能一般: "volumeNormal",
  量能資料不足: "volumeInsufficient",
  訊號資料不足: "signalInsufficient",
  尚無足夠資料產生報告: "notEnoughForReport",
  尚無足夠日K資料產生技術報告: "notEnoughDailyReport",
  尚無足夠週K資料產生技術報告: "notEnoughWeeklyReport",
  尚無足夠月K資料產生技術報告: "notEnoughMonthlyReport",
  正在整理技術訊號: "organizingSignals",
  觀察中: "observing",
  空方趨勢延續: "bearishTrend",
  多方趨勢延續: "bullishTrend",
  弱勢結構: "bearishStructure",
  偏多結構: "bullishStructure",
  均線結構轉換中: "transitioningStructure",
  結構資料不足: "insufficientStructure",
  超賣但尚未止跌: "oversoldNotReversed",
  超賣反彈觀察: "oversoldReboundWatch",
  "過熱，留意拉回": "overheatedPullbackRisk",
  動能仍偏弱: "weakMomentum",
  動能仍偏強: "strongMomentum",
  等待動能確認: "momentumConfirmationPending",
  趨勢證據: "trendEvidence",
  動能與超賣: "momentumOversold",
  量價確認: "volumeConfirmation",
  風險與區間: "riskRange",
  放量下跌: "downOnHighVolume",
  放量上漲: "upOnHighVolume",
  量價未明顯確認: "volumeNotConfirmed",
  接近20日區間底部: "nearRangeBottom",
  接近20日區間頂部: "nearRangeTop",
  位於20日區間中段: "rangeMiddle20",
  均線排列轉換中: "movingAverageTransition",
};

export function technicalReportPhrase(
  value: string,
  t?: TranslationFunction
) {
  const key = technicalTextKeyMap[value];
  return key
    ? translatedValue(t, `stockDetail.dataViews.technical.terms.${key}`, value)
    : value;
}

function translatedTechnicalDisplayValue(value: string, t?: TranslationFunction) {
  if (!t) return value;
  if (value === "觀察中") return technicalReportPhrase(value, t);
  if (/^\d+筆$/.test(value)) {
    return translatedValue(t, "stockDetail.dataViews.technical.units.points", value, {
      count: value.replace("筆", ""),
    });
  }
  if (value.endsWith("張")) {
    return `${value.slice(0, -1)}${t("stockDetail.dataPanel.units.lots")}`;
  }
  return value;
}

function replaceKnownTechnicalTerms(text: string, t?: TranslationFunction) {
  if (!t) return text;

  let output = text;
  Object.keys(technicalTextKeyMap)
    .sort((left, right) => right.length - left.length)
    .forEach((term) => {
      output = output.replaceAll(term, technicalReportPhrase(term, t));
    });

  return output
    .replaceAll("，", ", ")
    .replaceAll("日K", translatedValue(t, "stockDetail.dataViews.technical.terms.dailyK", "Daily"))
    .replaceAll("週K", translatedValue(t, "stockDetail.dataViews.technical.terms.weeklyK", "Weekly"))
    .replaceAll("月K", translatedValue(t, "stockDetail.dataViews.technical.terms.monthlyK", "Monthly"))
    .replaceAll("20日均量", translatedValue(t, "stockDetail.dataViews.technical.terms.twentyDayAverage", "20-day average"))
    .replaceAll("20期均量", translatedValue(t, "stockDetail.dataViews.technical.terms.twentyPeriodAverage", "20-period average"))
    .replaceAll("融資餘額", translatedValue(t, "stockDetail.dataViews.technical.terms.marginBalance", "margin balance"))
    .replaceAll("最新三大法人合計", translatedValue(t, "stockDetail.dataViews.technical.terms.latestInstitutionalTotal", "Latest institutional total"))
    .replaceAll("最新已公布三大法人", translatedValue(t, "stockDetail.dataViews.technical.terms.latestInstitutionalPublished", "Latest published institutional data"))
    .replaceAll("目前累計量", translatedValue(t, "stockDetail.dataViews.technical.terms.currentCumulativeVolume", "Current cumulative volume"))
    .replaceAll("今日漲跌幅將以上一交易日收盤價計算", translatedValue(t, "stockDetail.dataViews.technical.terms.todayReferenceClose", "Today's change is calculated from the previous close"))
    .replaceAll("尚未取得今日第一筆成交或即時快照", translatedValue(t, "stockDetail.dataViews.technical.terms.noIntradaySnapshot", "No first intraday trade or realtime snapshot yet"))
    .replaceAll("相對昨收", translatedValue(t, "stockDetail.dataViews.technical.terms.vsPreviousClose", "vs previous close"))
    .replaceAll("均價", translatedValue(t, "stockDetail.dataViews.technical.terms.averagePrice", "average price"))
    .replaceAll("高低", translatedValue(t, "stockDetail.dataViews.technical.terms.highLow", "high/low"))
    .replaceAll("持股比", translatedValue(t, "stockDetail.dataViews.technical.terms.holdingRatio", "holding ratio"))
    .replaceAll("最新", translatedValue(t, "stockDetail.dataViews.technical.terms.latest", "latest"))
    .replace(/(\d+)\s*筆盤中資料/g, (_, count: string) =>
      translatedValue(t, "stockDetail.dataViews.technical.units.intradayPoints", `${count} intraday points`, {
        count,
      })
    )
    .replace(/(\d+)週/g, (_, count: string) =>
      translatedValue(t, "stockDetail.dataViews.technical.units.weeks", `${count}W`, { count })
    )
    .replace(/(\d+)月/g, (_, count: string) =>
      translatedValue(t, "stockDetail.dataViews.technical.units.months", `${count}M`, { count })
    )
    .replace(/(\d+)筆/g, (_, count: string) =>
      translatedValue(t, "stockDetail.dataViews.technical.units.points", `${count} points`, {
        count,
      })
    )
    .replace(/([+-]?[0-9,]+(?:\.\d+)?)張/g, (_, count: string) =>
      `${count}${t("stockDetail.dataPanel.units.lots")}`
    );
}

function technicalValueLabel(value: string, t?: TranslationFunction) {
  if (value === "vs 昨收") {
    return translatedValue(t, "stockDetail.dataViews.technical.valueLabels.vsPreviousClose", value);
  }
  if (value === "近13週") {
    return translatedValue(t, "stockDetail.dataViews.technical.valueLabels.last13Weeks", value);
  }
  if (value === "近6月") {
    return translatedValue(t, "stockDetail.dataViews.technical.valueLabels.last6Months", value);
  }
  if (value === "近12月") {
    return translatedValue(t, "stockDetail.dataViews.technical.valueLabels.last12Months", value);
  }
  return value;
}

export function technicalToneClass(tone: TechnicalTone) {
  if (tone === "positive") return "text-omi-market-up";
  if (tone === "negative") return "text-omi-market-down";
  if (tone === "warning") return "text-omi-warning";
  return "text-omi-text";
}

export function semanticTechnicalTone(tone: string | null | undefined): TechnicalTone {
  if (tone === "positive" || tone === "negative" || tone === "warning") return tone;
  return "neutral";
}

export function semanticBadgeToneClass(tone: string | null | undefined) {
  if (tone === "positive") return "text-omi-danger bg-omi-danger-soft";
  if (tone === "negative") return "text-omi-success bg-omi-success-soft";
  if (tone === "warning") return "text-omi-warning bg-omi-warning-soft";
  return "text-omi-text-muted bg-omi-surface-muted";
}

export function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function integerValue(value: unknown) {
  const parsed = numberValue(value);
  return parsed === null ? 0 : Math.trunc(parsed);
}

function numericRecord(value: unknown) {
  const record = objectValue(value);
  if (!record) return {};
  return Object.fromEntries(
    Object.entries(record).map(([key, item]) => [key, numberValue(item)])
  );
}

function mapTechnicalCurrentState(
  value: unknown,
  t?: TranslationFunction
): TechnicalCurrentState | null {
  const root = objectValue(value);
  const headline = objectValue(root?.headline);
  const qualifier = objectValue(root?.qualifier);
  const position = objectValue(root?.position);
  if (!root || !headline || !qualifier || !position) return null;

  const levels = Array.isArray(root.levels)
    ? root.levels
        .map((item): TechnicalCurrentStateLevel | null => {
          const level = objectValue(item);
          if (!level || typeof level.key !== "string") return null;
          return {
            key: level.key,
            role: stringValue(level.role, "current"),
            label: technicalReportPhrase(stringValue(level.label, level.key), t),
            price: numberValue(level.price),
            moveRequiredPct: numberValue(level.move_required_pct),
            referenceDistancePct: numberValue(level.reference_distance_pct),
            tone: semanticTechnicalTone(stringValue(level.tone)),
          };
        })
        .filter((item): item is TechnicalCurrentStateLevel => item !== null)
    : [];
  const evidence = Array.isArray(root.evidence)
    ? root.evidence
        .map((item): TechnicalCurrentStateEvidence | null => {
          const evidenceItem = objectValue(item);
          if (!evidenceItem || typeof evidenceItem.key !== "string") return null;
          return {
            key: evidenceItem.key,
            label: technicalReportPhrase(
              stringValue(evidenceItem.label, evidenceItem.key),
              t
            ),
            stateKey: stringValue(evidenceItem.state_key),
            stateLabel: technicalReportPhrase(
              stringValue(evidenceItem.state_label),
              t
            ),
            tone: semanticTechnicalTone(stringValue(evidenceItem.tone)),
            summary: replaceKnownTechnicalTerms(
              stringValue(evidenceItem.summary),
              t
            ),
            metrics: numericRecord(evidenceItem.metrics),
          };
        })
        .filter((item): item is TechnicalCurrentStateEvidence => item !== null)
    : [];
  const nextConditions = Array.isArray(root.next_conditions)
    ? root.next_conditions
        .map((item): TechnicalCurrentStateCondition | null => {
          const condition = objectValue(item);
          if (!condition || typeof condition.key !== "string") return null;
          return {
            key: condition.key,
            label: replaceKnownTechnicalTerms(
              stringValue(condition.label, condition.key),
              t
            ),
            tone: semanticTechnicalTone(stringValue(condition.tone)),
            levelKey:
              typeof condition.level_key === "string"
                ? condition.level_key
                : null,
            price: numberValue(condition.price),
          };
        })
        .filter((item): item is TechnicalCurrentStateCondition => item !== null)
    : [];

  return {
    version: stringValue(root.version, "tw_technical_current_state_v1"),
    headline: {
      key: stringValue(headline.key),
      label: technicalReportPhrase(stringValue(headline.label), t),
      tone: semanticTechnicalTone(stringValue(headline.tone)),
    },
    qualifier: {
      key: stringValue(qualifier.key),
      label: technicalReportPhrase(stringValue(qualifier.label), t),
      tone: semanticTechnicalTone(stringValue(qualifier.tone)),
    },
    summary: replaceKnownTechnicalTerms(stringValue(root.summary), t),
    position: {
      price: numberValue(position.price),
      label: replaceKnownTechnicalTerms(stringValue(position.label), t),
      belowCount: integerValue(position.below_count),
      aboveCount: integerValue(position.above_count),
      availableCount: integerValue(position.available_count),
      order: Array.isArray(position.order)
        ? position.order.filter((item): item is string => typeof item === "string")
        : [],
      orderLabel: stringValue(position.order_label),
      alignment: stringValue(position.alignment),
      alignmentLabel: technicalReportPhrase(
        stringValue(position.alignment_label),
        t
      ),
      distancePct: numericRecord(position.distance_pct),
    },
    levels,
    evidence,
    nextConditions,
  };
}

export function mapBackendTechnicalReport(
  report: StockTechnicalReportRead,
  t?: TranslationFunction
): TechnicalReport {
  const priceContext =
    report.data.price_context &&
    typeof report.data.price_context === "object" &&
    !Array.isArray(report.data.price_context)
      ? (report.data.price_context as Record<string, unknown>)
      : null;
  const priceTime =
    typeof priceContext?.price_time === "string" ? priceContext.price_time : null;
  const dailyIndicatorTime =
    typeof priceContext?.daily_indicator_time === "string"
      ? priceContext.daily_indicator_time
      : null;
  const isIntraday = priceContext?.is_intraday === true;
  const currentStateStatus =
    typeof report.data.current_state_status === "string"
      ? report.data.current_state_status
      : null;
  const currentStateDecisionUsable =
    report.data.current_state_decision_usable !== false;
  const currentStateTime =
    typeof report.data.current_state_time === "string"
      ? report.data.current_state_time
      : null;
  const decisionStateTime =
    typeof report.data.decision_state_time === "string"
      ? report.data.decision_state_time
      : null;
  const decisionStateStatus =
    typeof report.data.decision_state_status === "string"
      ? report.data.decision_state_status
      : null;
  const currentObservationData =
    report.data.current_observation &&
    typeof report.data.current_observation === "object" &&
    !Array.isArray(report.data.current_observation)
      ? (report.data.current_observation as Record<string, unknown>)
      : null;
  const currentObservation = currentObservationData
    ? {
        status:
          typeof currentObservationData.status === "string"
            ? currentObservationData.status
            : null,
        time:
          typeof currentObservationData.time === "string"
            ? currentObservationData.time
            : null,
        decisionUsable: currentObservationData.decision_usable === true,
        officialDailyConfirmed:
          currentObservationData.official_daily_confirmed === true,
        currentState: mapTechnicalCurrentState(
          currentObservationData.current_state,
          t
        ),
      }
    : null;
  const basisLabel = !currentStateDecisionUsable
    ? translatedValue(
        t,
        "stockDetail.dataViews.technical.basis.provisional",
        `今日暫估指標 ${currentStateTime?.slice(0, 10) ?? "-"}（不可作 finalized decision）· 正式日線 ${dailyIndicatorTime?.slice(0, 10) ?? "-"}`,
        {
          currentTime: currentStateTime?.slice(0, 10) ?? "-",
          dailyTime: dailyIndicatorTime?.slice(0, 10) ?? "-",
        }
      )
    : isIntraday
    ? translatedValue(
        t,
        "stockDetail.dataViews.technical.basis.intraday",
        `盤中價 ${priceTime ?? "-"} · 日線指標 ${dailyIndicatorTime ?? "-"}`,
        {
          priceTime: priceTime?.replace("T", " ").slice(0, 16) ?? "-",
          dailyTime: dailyIndicatorTime?.slice(0, 10) ?? "-",
        }
      )
    : dailyIndicatorTime
      ? translatedValue(
          t,
          "stockDetail.dataViews.technical.basis.daily",
          `日線指標截至 ${dailyIndicatorTime.slice(0, 10)}`,
          { dailyTime: dailyIndicatorTime.slice(0, 10) }
        )
      : null;

  return {
    title: technicalReportPhrase(report.title, t),
    summary: replaceKnownTechnicalTerms(report.summary, t),
    value: report.value,
    valueLabel: technicalValueLabel(report.value_label, t),
    score: report.score,
    rows: report.rows.map((row) => ({
      key: row.key,
      title: technicalReportPhrase(row.label, t),
      description: replaceKnownTechnicalTerms(row.description, t),
      value: translatedTechnicalDisplayValue(row.display_value, t),
      pulseValue: numberValue(row.value),
      direction: row.direction,
      tone: semanticTechnicalTone(row.tone),
    })),
    badges: report.badges.map((badge) => ({
      label: technicalReportPhrase(badge.label, t),
      tone: semanticBadgeToneClass(badge.tone),
    })),
    currentState: mapTechnicalCurrentState(report.data.current_state, t),
    decisionState: mapTechnicalCurrentState(report.data.decision_state, t),
    decisionStateTime,
    decisionStateStatus,
    currentObservation,
    currentStateStatus,
    currentStateDecisionUsable,
    basisLabel,
    warningCount: report.warnings.length,
  };
}

export function localizeTechnicalReport(
  report: TechnicalReport,
  t?: TranslationFunction
): TechnicalReport {
  if (!t) return report;

  return {
    ...report,
    title: technicalReportPhrase(report.title, t),
    summary: replaceKnownTechnicalTerms(report.summary, t),
    valueLabel: technicalValueLabel(report.valueLabel, t),
    rows: report.rows.map((row) => ({
      ...row,
      title: technicalReportPhrase(row.title, t),
      description: replaceKnownTechnicalTerms(row.description, t),
      value: translatedTechnicalDisplayValue(row.value, t),
    })),
    badges: report.badges.map((badge) => ({
      ...badge,
      label: technicalReportPhrase(badge.label, t),
    })),
    currentState: report.currentState
      ? mapTechnicalCurrentState(
          {
            version: report.currentState.version,
            headline: report.currentState.headline,
            qualifier: report.currentState.qualifier,
            summary: report.currentState.summary,
            position: {
              price: report.currentState.position.price,
              label: report.currentState.position.label,
              below_count: report.currentState.position.belowCount,
              above_count: report.currentState.position.aboveCount,
              available_count: report.currentState.position.availableCount,
              order: report.currentState.position.order,
              order_label: report.currentState.position.orderLabel,
              alignment: report.currentState.position.alignment,
              alignment_label: report.currentState.position.alignmentLabel,
              distance_pct: report.currentState.position.distancePct,
            },
            levels: report.currentState.levels.map((level) => ({
              key: level.key,
              role: level.role,
              label: level.label,
              price: level.price,
              move_required_pct: level.moveRequiredPct,
              reference_distance_pct: level.referenceDistancePct,
              tone: level.tone,
            })),
            evidence: report.currentState.evidence.map((item) => ({
              key: item.key,
              label: item.label,
              state_key: item.stateKey,
              state_label: item.stateLabel,
              tone: item.tone,
              summary: item.summary,
              metrics: item.metrics,
            })),
            next_conditions: report.currentState.nextConditions.map((item) => ({
              key: item.key,
              label: item.label,
              tone: item.tone,
              level_key: item.levelKey,
              price: item.price,
            })),
          },
          t
        )
      : null,
  };
}

export function TechnicalSignalRow({
  title,
  description,
  value,
  pulseValue,
  direction,
  tone = "neutral",
}: {
  title: string;
  description: string;
  value: string;
  pulseValue?: number | string | null;
  direction?: number | null;
  tone?: TechnicalTone;
}) {
  return (
    <div className={`omi-technical-row omi-technical-row-${tone} flex items-start justify-between gap-4 border-t border-omi-border-subtle py-2 first:border-t-0 first:pt-0`}>
      <div className="min-w-0">
        <div className="text-sm font-bold text-omi-text-strong">{title}</div>
        <div className="mt-0.5 text-xs leading-4 text-omi-text-muted">{description}</div>
      </div>
      <div className={`omi-technical-score shrink-0 text-right text-sm font-bold ${technicalToneClass(tone)}`}>
        <PriceUpdatePulse
          value={pulseValue ?? value}
          direction={direction}
          resetKey={title}
          className="justify-end tabular-nums"
        >
          {value}
        </PriceUpdatePulse>
      </div>
    </div>
  );
}

function currentStateLevelClass(level: TechnicalCurrentStateLevel) {
  if (level.role === "risk" || level.role === "broken_support") {
    return "border-omi-market-down-border bg-omi-market-down-soft";
  }
  if (level.role === "reclaim" || level.role === "resistance") {
    return "border-omi-warning-border bg-omi-warning-soft";
  }
  if (level.role === "support") {
    return "border-omi-success-border bg-omi-success-soft";
  }
  return "border-omi-border-subtle bg-omi-surface-muted";
}

function currentStateLevelLabel(
  level: TechnicalCurrentStateLevel,
  t: TranslationFunction
) {
  if (level.key === "support20") {
    return t("stockDetail.technicalCurrentState.levels.risk");
  }
  if (level.key === "resistance20") {
    return t("stockDetail.technicalCurrentState.levels.resistance");
  }
  const average = level.key.toUpperCase();
  if (level.role === "reclaim") {
    return t("stockDetail.technicalCurrentState.levels.reclaim", { average });
  }
  if (level.role === "support") {
    return t("stockDetail.technicalCurrentState.levels.support", { average });
  }
  return level.label;
}

function currentStateMoveLabel(
  level: TechnicalCurrentStateLevel,
  t: TranslationFunction
) {
  if (level.moveRequiredPct === null) return "-";
  if (level.role === "reclaim" || level.role === "resistance") {
    return t("stockDetail.technicalCurrentState.move.reclaim", {
      value: formatPct(level.moveRequiredPct),
    });
  }
  if (level.role === "risk" || level.role === "broken_support") {
    return t("stockDetail.technicalCurrentState.move.risk", {
      value: formatPct(level.moveRequiredPct),
    });
  }
  if (level.role === "support") {
    return t("stockDetail.technicalCurrentState.move.support", {
      value: formatPct(level.moveRequiredPct),
    });
  }
  return formatPct(level.moveRequiredPct);
}

function currentStateConditionLabel(
  condition: TechnicalCurrentStateCondition,
  t: TranslationFunction
) {
  const average = condition.levelKey?.toUpperCase() ?? "-";
  const price = formatPrice(condition.price);
  if (condition.key === "first_reclaim") {
    return t("stockDetail.technicalCurrentState.conditions.firstReclaim", {
      average,
      price,
    });
  }
  if (condition.key === "structure_repair") {
    return t("stockDetail.technicalCurrentState.conditions.structureRepair", {
      average,
      price,
    });
  }
  if (condition.key === "first_defense") {
    return t("stockDetail.technicalCurrentState.conditions.firstDefense", {
      average,
      price,
    });
  }
  if (condition.key === "risk_break") {
    return t("stockDetail.technicalCurrentState.conditions.riskBreak", {
      price,
    });
  }
  return condition.label;
}

export function TechnicalCurrentStateOverview({
  state,
}: {
  state: TechnicalCurrentState;
}) {
  const t = useT();

  return (
    <section
      className="space-y-2 border-b border-omi-border-subtle px-5 py-3"
      data-testid="tw-technical-current-state"
    >
      <StockDetailDisclosure
        testId="tw-technical-ladder-disclosure"
        title={t("stockDetail.technicalCurrentState.ladderTitle")}
        description={t("stockDetail.technicalCurrentState.ladderHint")}
        summaryClassName="px-1 py-1.5"
        contentClassName="pb-1 pt-2"
        trailing={
          <span className="text-right">
            <span className="block text-sm font-semibold tabular-nums text-omi-text-strong">
              {formatPrice(state.position.price)}
            </span>
            <span className="block text-xs text-omi-text-muted">
              {t("stockDetail.technicalCurrentState.currentPrice")}
            </span>
          </span>
        }
      >
        <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
          {state.levels.map((level) => (
            <div
              key={level.key}
              className={`min-w-0 border px-2.5 py-2 ${currentStateLevelClass(level)}`}
              data-level-key={level.key}
            >
              <div className="truncate text-[11px] font-medium text-omi-text-muted">
                {currentStateLevelLabel(level, t)}
              </div>
              <div className="mt-0.5 text-sm font-semibold tabular-nums text-omi-text-strong">
                {formatPrice(level.price)}
              </div>
              <div className={`mt-0.5 text-[11px] leading-4 tabular-nums ${technicalToneClass(level.tone)}`}>
                {currentStateMoveLabel(level, t)}
              </div>
            </div>
          ))}
        </div>
      </StockDetailDisclosure>

      {state.nextConditions.length ? (
        <StockDetailDisclosure
          testId="tw-technical-next-conditions-disclosure"
          className="border-t border-omi-border-subtle"
          title={t("stockDetail.technicalCurrentState.nextConditions")}
          summaryClassName="px-1 py-2"
          contentClassName="pb-1 pt-1"
        >
          <ol className="space-y-1.5">
            {state.nextConditions.map((condition, index) => (
              <li
                key={condition.key}
                className="flex gap-2 text-xs leading-5 text-omi-text-muted"
              >
                <span
                  className={`shrink-0 font-bold tabular-nums ${technicalToneClass(condition.tone)}`}
                >
                  {index + 1}
                </span>
                <span>{currentStateConditionLabel(condition, t)}</span>
              </li>
            ))}
          </ol>
        </StockDetailDisclosure>
      ) : null}
    </section>
  );
}

export function TechnicalCurrentStateEvidence({
  children,
  state,
}: {
  children?: ReactNode;
  state: TechnicalCurrentState;
}) {
  const t = useT();

  return (
    <StockDetailDisclosure
      testId="tw-technical-evidence-disclosure"
      title={t("stockDetail.technicalCurrentState.evidenceTitle")}
      description={t("stockDetail.technicalCurrentState.evidenceHint")}
      summaryClassName="px-1 py-1.5"
      contentClassName="space-y-2 pt-2"
    >
      {state.evidence.map((item) => (
        <details
          key={item.key}
          id={`tw-technical-evidence-${item.key}`}
          className="group/evidence-item border border-omi-border-subtle bg-omi-surface-muted"
          data-testid={`tw-technical-evidence-${item.key}`}
        >
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3.5 py-2.5 outline-none transition hover:bg-omi-surface focus-visible:ring-2 focus-visible:ring-omi-accent [&::-webkit-details-marker]:hidden">
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-omi-text-strong">
                {item.label}
              </span>
              <span className={`mt-0.5 block truncate text-xs leading-4 ${technicalToneClass(item.tone)}`}>
                {item.stateLabel}
              </span>
            </span>
            <span
              aria-hidden="true"
              className="shrink-0 text-base text-omi-text-muted transition-transform group-open/evidence-item:rotate-45"
            >
              ＋
            </span>
          </summary>
          <div className="border-t border-omi-border-subtle px-3.5 py-2.5 text-sm leading-6 text-omi-text-muted">
            {item.summary}
          </div>
        </details>
      ))}
      {children}
    </StockDetailDisclosure>
  );
}

export function TechnicalLoadingPanel() {
  const t = useT();

  return (
    <>
      <div className="omi-technical-summary border-b border-omi-border-subtle px-5 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            Technical
          </div>
          <LoadingDots label={t("stockDetail.dataViews.technicalLoading")} />
        </div>
        <div className="mt-3 flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="omi-skeleton h-5 w-32" />
            <div className="omi-skeleton h-3 w-56 max-w-full" />
          </div>
          <div className="w-20 space-y-2">
            <div className="ml-auto omi-skeleton h-5 w-16" />
            <div className="ml-auto omi-skeleton h-2.5 w-12" />
          </div>
        </div>
      </div>

      <div className="px-5 py-3">
        <div className="space-y-0">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              className="omi-technical-loading-row flex items-start justify-between gap-4 border-t border-omi-border-subtle py-2 first:border-t-0 first:pt-0"
              aria-hidden="true"
            >
              <div className="min-w-0 flex-1 space-y-2">
                <div className="omi-skeleton h-3.5 w-24" />
                <div className="omi-skeleton h-2.5 w-48 max-w-full" />
              </div>
              <div className="w-20 space-y-2">
                <div className="ml-auto omi-skeleton h-3.5 w-14" />
                <div className="ml-auto omi-skeleton h-2.5 w-10" />
              </div>
            </div>
          ))}
        </div>

        <div className="mt-3 border-t border-omi-border-subtle pt-3">
          <div className="omi-technical-loading-row flex items-start justify-between gap-4 text-xs">
            <div className="space-y-2">
              <div className="omi-skeleton h-3 w-16" />
              <div className="omi-skeleton h-4 w-20" />
              <div className="omi-skeleton h-2.5 w-24" />
            </div>
            <div className="w-20 space-y-2">
              <div className="ml-auto omi-skeleton h-3.5 w-16" />
              <div className="ml-auto omi-skeleton h-2.5 w-12" />
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2" aria-hidden="true">
          <div className="omi-skeleton h-7 w-20" />
          <div className="omi-skeleton h-7 w-24" />
          <div className="omi-skeleton h-7 w-16" />
        </div>
      </div>
    </>
  );
}

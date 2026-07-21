"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import { useT, type TranslationFunction, type TranslationValues } from "@/i18n";
import type { StockTechnicalReportRead } from "@/types/market";

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

export type TechnicalReport = {
  title: string;
  summary: string;
  value: number | null;
  valueLabel: string;
  score: number;
  rows: TechnicalReportRow[];
  badges: TechnicalReportBadge[];
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
  const basisLabel = isIntraday
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

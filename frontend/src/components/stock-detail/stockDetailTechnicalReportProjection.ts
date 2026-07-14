import {
  averageRecentChartClose,
  chartWindowStats,
  finiteNumber,
  formatDate,
  formatIndicatorValue,
  formatLots,
  formatPct,
  formatPrice,
  formatRatioPct,
  formatSignedLots,
  formatSignedNumber,
  latestLargeHolderSummary,
  marketRegimeLabel,
  safeRatio,
  sumRecentInstitutionalNet,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  LoadState,
  TechnicalReport,
  TechnicalReportBadge,
  TechnicalReportRow,
  TechnicalTone,
  Timeframe,
} from "@/components/stock-detail/StockDetailDataViews";
import { timeframeLabel, type TranslationFunction } from "@/i18n";
import {
  TAIWAN_SESSION_START_MINUTES,
  getTaipeiMinutesOfDay,
} from "@/lib/taiwanMarketTime";
import type {
  ChartPoint,
  FinancialMetricQuarterlyRead,
  InstitutionalTradeDailyRead,
  IntradayTrendPoint,
  MarginTradingDailyRead,
  MarketIndexSnapshot,
  MonthlyRevenueRead,
  ShareholdingDistributionWeeklyRead,
  StockIndicatorPoint,
} from "@/types/market";

const openingObservationMinutes = 5;
const openingObservationMinPoints = 5;

export type FallbackTechnicalReportInput = {
  chartData: ChartPoint[];
  currentChartReady: boolean;
  effectiveTimeframe: Timeframe;
  financialMetric: FinancialMetricQuarterlyRead | null;
  institutional: InstitutionalTradeDailyRead | null;
  institutionalHistory: InstitutionalTradeDailyRead[];
  isIndexProduct: boolean;
  largeHolderLots: number;
  latestChangePct: number | null;
  latestChartVolume: number | null;
  latestClose: number | null;
  latestCurrentIndicator: StockIndicatorPoint | null;
  latestToday: IntradayTrendPoint | null;
  loadState: LoadState;
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
  margin: MarginTradingDailyRead | null;
  monthlyRevenue: MonthlyRevenueRead | null;
  primaryMarketIndex: MarketIndexSnapshot | null;
  priceVsMa20: number | null;
  relativeToPrimaryIndex: number | null;
  shareholding: ShareholdingDistributionWeeklyRead[];
  t: TranslationFunction;
  todayStats: {
    open: number | null;
    high: number | null;
    low: number | null;
    volume: number | null;
  };
  todayReferenceClose: number | null;
  todayTrendLength: number;
  totalInstitutionalNet: number | null;
  volumeMa20: number | null;
  volumeRatio: number | null;
  volumeRatioPct: number | null;
};

export function buildFallbackTechnicalReport({
  chartData,
  currentChartReady,
  effectiveTimeframe,
  financialMetric,
  institutional,
  institutionalHistory,
  isIndexProduct,
  largeHolderLots,
  latestChangePct,
  latestChartVolume,
  latestClose,
  latestCurrentIndicator,
  latestToday,
  loadState,
  ma5,
  ma20,
  ma60,
  margin,
  monthlyRevenue,
  primaryMarketIndex,
  priceVsMa20,
  relativeToPrimaryIndex,
  shareholding,
  t,
  todayStats,
  todayReferenceClose,
  todayTrendLength,
  totalInstitutionalNet,
  volumeMa20,
  volumeRatio,
  volumeRatioPct,
}: FallbackTechnicalReportInput): TechnicalReport {
    const rows: TechnicalReportRow[] = [];
    const badges: TechnicalReportBadge[] = [];
    let score = 0;
    const hasCurrentChart =
      effectiveTimeframe === "today" || currentChartReady || isIndexProduct;

    function addScore(value: number) {
      score += value;
    }

    function addBadge(label: string, tone: string) {
      if (badges.some((badge) => badge.label === label)) return;
      badges.push({ label, tone });
    }

    function rowTone(value: number | null | undefined): TechnicalTone {
      if (!finiteNumber(value)) return "neutral";
      if (value > 0) return "positive";
      if (value < 0) return "negative";
      return "neutral";
    }

    function titleFor(shortLabel: string, neutralLabel: string, weakLabel: string) {
      if (score >= 3) return shortLabel;
      if (score <= -3) return weakLabel;
      return neutralLabel;
    }

    function summaryFrom(parts: string[]) {
      if (loadState === "loading") return "資料讀取中";
      const validParts = parts.filter((part) => part && part !== "資料不足");
      return validParts.length ? validParts.join("，") : "訊號資料不足";
    }

    if (effectiveTimeframe === "today" && !latestToday) {
      addBadge("等待盤中", "text-omi-text-muted bg-omi-surface-muted");

      return {
        title: loadState === "loading" ? "資料讀取中" : "等待盤中資料",
        summary:
          loadState === "loading"
            ? "正在取得今日盤中資料"
            : "尚未取得今日第一筆成交，日線資料暫不作盤中判斷",
        value: null,
        valueLabel: "vs 昨收",
        score: 0,
        rows: [
          {
            title: "資料狀態",
            description: "尚未取得今日第一筆成交或即時快照",
            value: "0筆",
            tone: "neutral",
          },
          {
            title: "參考基準",
            description: "今日漲跌幅將以上一交易日收盤價計算",
            value: formatPrice(todayReferenceClose),
            pulseValue: todayReferenceClose,
            tone: "neutral",
          },
        ],
        badges,
      };
    }

    if (!finiteNumber(latestClose) || !hasCurrentChart) {
      return {
        title: loadState === "loading" ? "資料讀取中" : "資料不足",
        summary: loadState === "loading" ? "正在整理技術訊號" : "尚無足夠資料產生報告",
        value: null,
        valueLabel: timeframeLabel(t, effectiveTimeframe),
        score: 0,
        rows: [
          {
            title: "資料狀態",
            description: hasCurrentChart ? "價格資料不足" : "等待目前週期 K 線資料",
            value: "-",
            tone: "neutral",
          },
        ],
        badges,
      };
    }

    const rsi14 = latestCurrentIndicator?.rsi?.rsi14 ?? null;
    const macdHistogram = latestCurrentIndicator?.macd?.histogram ?? null;
    const roc12 = latestCurrentIndicator?.roc?.roc12 ?? null;
    const mfi14 = latestCurrentIndicator?.mfi?.mfi14 ?? null;
    const atr14 = latestCurrentIndicator?.atr?.atr14 ?? null;
    const adx14 = latestCurrentIndicator?.adx?.adx14 ?? null;
    const plusDi14 = latestCurrentIndicator?.adx?.plus_di14 ?? null;
    const minusDi14 = latestCurrentIndicator?.adx?.minus_di14 ?? null;
    const donchianUpper20 = latestCurrentIndicator?.donchian?.upper20 ?? null;
    const donchianLower20 = latestCurrentIndicator?.donchian?.lower20 ?? null;
    const atrPct =
      finiteNumber(atr14) && latestClose !== 0 ? (atr14 / latestClose) * 100 : null;
    const donchianPositionPct =
      finiteNumber(donchianUpper20) &&
      finiteNumber(donchianLower20) &&
      donchianUpper20 !== donchianLower20
        ? ((latestClose - donchianLower20) / (donchianUpper20 - donchianLower20)) * 100
        : null;
    const latestInstitutionalNet =
      institutional?.total_institutional_net ?? totalInstitutionalNet;
    const largeHolder = latestLargeHolderSummary(shareholding, largeHolderLots);
    const marginBalanceChange =
      finiteNumber(margin?.margin_today_balance) && finiteNumber(margin?.margin_previous_balance)
        ? margin.margin_today_balance - margin.margin_previous_balance
        : null;
    const marketRelativeLabel =
      relativeToPrimaryIndex === null
        ? "資料不足"
        : relativeToPrimaryIndex > 0
          ? "強於大盤"
          : relativeToPrimaryIndex < 0
            ? "弱於大盤"
            : "同步大盤";

    if (effectiveTimeframe === "today") {
      const pointCount = todayTrendLength;
      const latestIntradayMinutes = latestToday ? getTaipeiMinutesOfDay(latestToday.time) : null;
      const minutesFromOpen = finiteNumber(latestIntradayMinutes)
        ? latestIntradayMinutes - TAIWAN_SESSION_START_MINUTES
        : null;
      const isOpeningPhase =
        !finiteNumber(minutesFromOpen) ||
        minutesFromOpen < openingObservationMinutes ||
        pointCount < openingObservationMinPoints;
      const todayOpen = todayStats.open ?? latestToday?.open ?? null;
      const priceVsOpenPct =
        finiteNumber(latestClose) && finiteNumber(todayOpen) && todayOpen !== 0
          ? ((latestClose - todayOpen) / todayOpen) * 100
          : null;
      const openingGapPct =
        finiteNumber(todayOpen) && finiteNumber(todayReferenceClose) && todayReferenceClose !== 0
          ? ((todayOpen - todayReferenceClose) / todayReferenceClose) * 100
          : null;
      const intradayRangePct =
        finiteNumber(todayStats.high) &&
        finiteNumber(todayStats.low) &&
        finiteNumber(todayReferenceClose) &&
        todayReferenceClose !== 0
          ? ((todayStats.high - todayStats.low) / todayReferenceClose) * 100
          : null;
      const currentVolume = todayStats.volume ?? latestToday?.volume ?? null;
      const currentVolumeVsDailyAverage = safeRatio(currentVolume, volumeMa20);
      const currentVolumeVsDailyAveragePct =
        currentVolumeVsDailyAverage === null ? null : currentVolumeVsDailyAverage * 100;


      if (finiteNumber(latestChangePct)) {
        if (latestChangePct > 0) addScore(1);
        if (latestChangePct < 0) addScore(-1);
      }
      if (finiteNumber(openingGapPct)) {
        if (openingGapPct > 0) addScore(1);
        if (openingGapPct < 0) addScore(-1);
      }
      if (!isOpeningPhase && finiteNumber(priceVsOpenPct)) {
        if (priceVsOpenPct > 0) addScore(1);
        if (priceVsOpenPct < 0) addScore(-1);
      }
      if (!isOpeningPhase && finiteNumber(relativeToPrimaryIndex)) {
        if (relativeToPrimaryIndex > 0) addScore(1);
        if (relativeToPrimaryIndex < 0) addScore(-1);
      }

      const intradayHighLow = `${formatPrice(todayStats.high)} / ${formatPrice(todayStats.low)}`;
      rows.push(
        {
          title: "即時價格",
          description: `相對昨收 ${formatPct(latestChangePct)}，${pointCount} 筆盤中資料`,
          value: formatPrice(latestClose),
          pulseValue: latestClose,
          direction: latestChangePct,
          tone: rowTone(latestChangePct),
        },
        {
          title: "開盤結構",
          description: `開盤 ${formatPrice(todayOpen)}，高低 ${intradayHighLow}，振幅 ${formatPct(intradayRangePct)}`,
          value: formatPct(priceVsOpenPct),
          pulseValue: priceVsOpenPct,
          direction: priceVsOpenPct,
          tone: rowTone(priceVsOpenPct),
        },
        {
          title: "量能速度",
          description: `目前累計量，20日均量占比 ${formatPct(currentVolumeVsDailyAveragePct)}`,
          value: currentVolume === null ? "觀察中" : `${formatLots(currentVolume)}張`,
          pulseValue: currentVolume,
          direction: null,
          tone: "neutral",
        },
        {
          title: "日線背景",
          description: `RSI ${formatIndicatorValue(rsi14)}，MACD H ${formatIndicatorValue(macdHistogram)}，MA20 ${formatPrice(ma20)}`,
          value: formatPct(priceVsMa20),
          pulseValue: priceVsMa20,
          direction: priceVsMa20,
          tone:
            finiteNumber(rsi14) && rsi14 >= 80
              ? "warning"
              : finiteNumber(priceVsMa20)
                ? rowTone(priceVsMa20)
                : "neutral",
        },
        {
          title: "法人籌碼",
          description: `最新已公布三大法人，融資餘額 ${formatSignedNumber(marginBalanceChange)}`,
          value:
            latestInstitutionalNet === null
              ? "-"
              : `${formatSignedLots(latestInstitutionalNet)}張`,
          pulseValue: latestInstitutionalNet,
          direction: latestInstitutionalNet,
          tone: rowTone(latestInstitutionalNet),
        },
        {
          title: "相對市場",
          description: `相對${primaryMarketIndex?.short_label ?? "大盤"}，${
            isOpeningPhase ? "開盤初期僅作方向參考" : marketRelativeLabel
          }`,
          value: formatPct(relativeToPrimaryIndex),
          pulseValue: relativeToPrimaryIndex,
          direction: relativeToPrimaryIndex,
          tone: rowTone(relativeToPrimaryIndex),
        }
      );

      if (isOpeningPhase) addBadge("開盤資料少", "text-omi-warning bg-omi-warning-soft");
      if (finiteNumber(openingGapPct)) {
        addBadge(
          openingGapPct >= 0 ? "開高" : "開低",
          openingGapPct >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft"
        );
      }
      if (finiteNumber(priceVsMa20)) {
        addBadge(
          priceVsMa20 >= 0 ? "日線站上 MA20" : "日線跌破 MA20",
          priceVsMa20 >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft"
        );
      }
      if (finiteNumber(rsi14) && rsi14 >= 80) addBadge("日線 RSI 過熱", "text-omi-warning bg-omi-warning-soft");

      return {
        title: isOpeningPhase
          ? titleFor("開盤偏強", "開盤觀察", "開盤偏弱")
          : titleFor("盤中偏多", "盤中觀察", "盤中偏弱"),
        summary: summaryFrom([
          `${pointCount} 筆盤中資料`,
          finiteNumber(latestChangePct)
            ? latestChangePct >= 0
              ? "現價高於昨收"
              : "現價低於昨收"
            : "資料不足",
          finiteNumber(openingGapPct)
            ? openingGapPct >= 0
              ? "開高"
              : "開低"
            : "資料不足",
          isOpeningPhase ? "日線指標僅作背景" : marketRelativeLabel,
        ]),
        value: latestChangePct ?? null,
        valueLabel: "vs 昨收",
        score,
        rows,
        badges,
      };
    }

    if (effectiveTimeframe === "daily") {
      if (finiteNumber(priceVsMa20)) addScore(priceVsMa20 >= 0 ? 1 : -1);
      if (finiteNumber(ma5) && finiteNumber(ma20)) addScore(ma5 >= ma20 ? 1 : -1);
      if (finiteNumber(ma20) && finiteNumber(ma60)) addScore(ma20 >= ma60 ? 1 : -1);
      if (finiteNumber(macdHistogram)) addScore(macdHistogram >= 0 ? 1 : -1);
      if (finiteNumber(rsi14)) {
        if (rsi14 >= 50 && rsi14 < 80) addScore(1);
        if (rsi14 < 40) addScore(-1);
      }
      if (finiteNumber(mfi14) && mfi14 >= 50 && mfi14 < 85) addScore(1);
      if (finiteNumber(adx14) && adx14 >= 25 && finiteNumber(plusDi14) && finiteNumber(minusDi14)) {
        addScore(plusDi14 >= minusDi14 ? 1 : -1);
      }
      if (finiteNumber(latestInstitutionalNet)) addScore(latestInstitutionalNet > 0 ? 1 : -1);

      rows.push(
        {
          title: "趨勢結構",
          description: `MA5/20/60 ${formatPrice(ma5)} / ${formatPrice(ma20)} / ${formatPrice(ma60)}，ADX ${formatIndicatorValue(adx14)}`,
          value: formatPct(priceVsMa20),
          pulseValue: priceVsMa20,
          direction: priceVsMa20,
          tone: rowTone(priceVsMa20),
        },
        {
          title: "動能指標",
          description: `RSI ${formatIndicatorValue(rsi14)}，MACD H ${formatIndicatorValue(macdHistogram)}，ROC12 ${formatPct(roc12)}`,
          value: formatIndicatorValue(rsi14),
          pulseValue: rsi14,
          direction: macdHistogram,

          tone:
            finiteNumber(rsi14) && rsi14 >= 80
              ? "warning"
              : finiteNumber(macdHistogram)
                ? rowTone(macdHistogram)
                : "neutral",
        },
        {
          title: "量價資金",
          description: `量能 ${formatPct(volumeRatioPct)} vs 20 日均量，MFI ${formatIndicatorValue(mfi14)}`,
          value: formatPct(volumeRatioPct),
          pulseValue: volumeRatioPct,
          direction: volumeRatioPct,
          tone: finiteNumber(volumeRatio) && volumeRatio >= 1.5 ? "warning" : "neutral",
        },
        {
          title: "波動風險",
          description: `ATR ${formatPct(atrPct)}，Donchian 位置 ${formatPct(donchianPositionPct)}`,
          value: formatPct(atrPct),
          pulseValue: atrPct,
          direction: finiteNumber(atrPct) && atrPct > 5 ? 1 : 0,
          tone: finiteNumber(atrPct) && atrPct > 5 ? "warning" : "neutral",
        },
        {
          title: "法人籌碼",
          description: `最新三大法人合計，融資餘額 ${formatSignedNumber(marginBalanceChange)}`,
          value:
            latestInstitutionalNet === null
              ? "-"
              : `${formatSignedLots(latestInstitutionalNet)}張`,
          pulseValue: latestInstitutionalNet,
          direction: latestInstitutionalNet,
          tone: rowTone(latestInstitutionalNet),
        },
        {
          title: "相對市場",
          description: `相對${primaryMarketIndex?.short_label ?? "大盤"}，${marketRelativeLabel}`,
          value: formatPct(relativeToPrimaryIndex),
          pulseValue: relativeToPrimaryIndex,
          direction: relativeToPrimaryIndex,
          tone: rowTone(relativeToPrimaryIndex),
        }
      );

      if (finiteNumber(priceVsMa20)) addBadge(priceVsMa20 >= 0 ? "站上 MA20" : "跌破 MA20", priceVsMa20 >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
      if (finiteNumber(macdHistogram)) addBadge(macdHistogram >= 0 ? "MACD 偏多" : "MACD 偏弱", macdHistogram >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
      if (finiteNumber(rsi14) && rsi14 >= 80) addBadge("RSI 過熱", "text-omi-warning bg-omi-warning-soft");
      if (finiteNumber(volumeRatio) && volumeRatio >= 1.5) addBadge("放量", "text-omi-warning bg-omi-warning-soft");

      return {
        title: titleFor("短線偏多", "短線整理", "短線偏弱"),
        summary: summaryFrom([
          finiteNumber(priceVsMa20) ? (priceVsMa20 >= 0 ? "站上 MA20" : "跌破 MA20") : "資料不足",
          finiteNumber(macdHistogram) ? (macdHistogram >= 0 ? "MACD 偏多" : "MACD 偏弱") : "資料不足",
          finiteNumber(volumeRatio) ? (volumeRatio >= 1.5 ? "放量" : "量能一般") : "資料不足",
        ]),
        value: priceVsMa20,
        valueLabel: "vs MA20",
        score,
        rows,
        badges,
      };
    }

    if (effectiveTimeframe === "weekly") {
      const weekStats13 = chartWindowStats(chartData, 13);
      const weekStats26 = chartWindowStats(chartData, 26);
      const weeklyMa4 = averageRecentChartClose(chartData, 4);
      const weeklyMa13 = averageRecentChartClose(chartData, 13);
      const weeklyVolumeRatio = safeRatio(latestChartVolume, weekStats13.volumeAverage);
      const weeklyVolumeRatioPct =
        weeklyVolumeRatio === null ? null : (weeklyVolumeRatio - 1) * 100;
      const institutional20 = sumRecentInstitutionalNet(institutionalHistory, 20) ?? latestInstitutionalNet;

      if (finiteNumber(weekStats13.changePct)) addScore(weekStats13.changePct >= 0 ? 1 : -1);
      if (finiteNumber(weeklyMa4) && finiteNumber(weeklyMa13)) addScore(weeklyMa4 >= weeklyMa13 ? 1 : -1);
      if (finiteNumber(weekStats26.rangePositionPct)) {
        if (weekStats26.rangePositionPct >= 65) addScore(1);
        if (weekStats26.rangePositionPct <= 35) addScore(-1);
      }
      if (finiteNumber(institutional20)) addScore(institutional20 > 0 ? 1 : -1);

      rows.push(
        {
          title: "中線趨勢",
          description: `4週/13週均價 ${formatPrice(weeklyMa4)} / ${formatPrice(weeklyMa13)}`,
          value: formatPct(weekStats13.changePct),
          pulseValue: weekStats13.changePct,
          direction: weekStats13.changePct,
          tone: rowTone(weekStats13.changePct),
        },
        {
          title: "區間位置",
          description: `26週高低 ${formatPrice(weekStats26.high)} / ${formatPrice(weekStats26.low)}`,
          value: formatPct(weekStats26.rangePositionPct),
          pulseValue: weekStats26.rangePositionPct,
          direction:
            finiteNumber(weekStats26.rangePositionPct) ? weekStats26.rangePositionPct - 50 : null,
          tone:
            finiteNumber(weekStats26.rangePositionPct) && weekStats26.rangePositionPct >= 70
              ? "positive"
              : finiteNumber(weekStats26.rangePositionPct) && weekStats26.rangePositionPct <= 30
                ? "negative"
                : "neutral",
        },
        {
          title: "週量節奏",
          description: "最新週量相對 13 週均量",
          value: formatPct(weeklyVolumeRatioPct),
          pulseValue: weeklyVolumeRatioPct,
          direction: weeklyVolumeRatioPct,
          tone: finiteNumber(weeklyVolumeRatio) && weeklyVolumeRatio >= 1.5 ? "warning" : "neutral",
        },
        {
          title: "法人累積",
          description: "近 20 個交易日三大法人合計",
          value: institutional20 === null ? "-" : `${formatSignedLots(institutional20)}張`,
          pulseValue: institutional20,
          direction: institutional20,
          tone: rowTone(institutional20),
        },
        {
          title: "市場背景",
          description: `${primaryMarketIndex?.short_label ?? t("stockDetail.marketFallback")} ${marketRegimeLabel(primaryMarketIndex, t)}`,
          value: formatPct(primaryMarketIndex?.change_pct),
          pulseValue: primaryMarketIndex?.change_pct,
          direction: primaryMarketIndex?.change_pct,
          tone: rowTone(primaryMarketIndex?.change_pct),
        }
      );

      if (finiteNumber(weeklyMa4) && finiteNumber(weeklyMa13)) addBadge(weeklyMa4 >= weeklyMa13 ? "週線偏多" : "週線偏弱", weeklyMa4 >= weeklyMa13 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
      if (finiteNumber(weekStats26.rangePositionPct) && weekStats26.rangePositionPct >= 80) addBadge("接近26週高位", "text-omi-warning bg-omi-warning-soft");
      if (finiteNumber(weeklyVolumeRatio) && weeklyVolumeRatio >= 1.5) addBadge("週量放大", "text-omi-warning bg-omi-warning-soft");

      return {
        title: titleFor("中線轉強", "中線整理", "中線偏弱"),
        summary: summaryFrom([
          finiteNumber(weekStats13.changePct) ? `13週${weekStats13.changePct >= 0 ? "走升" : "走弱"}` : "資料不足",
          finiteNumber(weekStats26.rangePositionPct)
            ? weekStats26.rangePositionPct >= 65
              ? "位於區間上緣"
              : weekStats26.rangePositionPct <= 35
                ? "位於區間下緣"
                : "區間中段"
            : "資料不足",
          institutional20 !== null ? (institutional20 >= 0 ? "法人累積買超" : "法人累積賣超") : "資料不足",
        ]),
        value: weekStats13.changePct,
        valueLabel: "近13週",

        score,
        rows,
        badges,
      };
    }

    const monthStats6 = chartWindowStats(chartData, 6);
    const monthStats12 = chartWindowStats(chartData, 12);
    const monthlyMa6 = averageRecentChartClose(chartData, 6);
    const monthlyMa12 = averageRecentChartClose(chartData, 12);
    const revenueGrowth = monthlyRevenue?.year_over_year_pct ?? null;
    const cumulativeRevenueGrowth = monthlyRevenue?.cumulative_year_over_year_pct ?? null;
    const eps = financialMetric?.eps ?? null;
    const roe = financialMetric?.roe ?? null;

    if (finiteNumber(monthStats12.changePct)) addScore(monthStats12.changePct >= 0 ? 1 : -1);
    if (finiteNumber(monthlyMa6) && finiteNumber(monthlyMa12)) addScore(monthlyMa6 >= monthlyMa12 ? 1 : -1);
    if (finiteNumber(revenueGrowth)) addScore(revenueGrowth >= 0 ? 1 : -1);
    if (finiteNumber(eps)) addScore(eps > 0 ? 1 : -1);
    if (finiteNumber(largeHolder.change)) addScore(largeHolder.change >= 0 ? 1 : -1);

    rows.push(
      {
        title: "長線趨勢",
        description: `6月/12月均價 ${formatPrice(monthlyMa6)} / ${formatPrice(monthlyMa12)}`,
        value: formatPct(monthStats12.changePct),
        pulseValue: monthStats12.changePct,
        direction: monthStats12.changePct,
        tone: rowTone(monthStats12.changePct),
      },
      {
        title: "長期區間",
        description: `12月高低 ${formatPrice(monthStats12.high)} / ${formatPrice(monthStats12.low)}`,
        value: formatPct(monthStats12.rangePositionPct),
        pulseValue: monthStats12.rangePositionPct,
        direction:
          finiteNumber(monthStats12.rangePositionPct) ? monthStats12.rangePositionPct - 50 : null,
        tone:
          finiteNumber(monthStats12.rangePositionPct) && monthStats12.rangePositionPct >= 70
            ? "positive"
            : finiteNumber(monthStats12.rangePositionPct) && monthStats12.rangePositionPct <= 30
              ? "negative"
              : "neutral",
      },
      {
        title: "營收動能",
        description: `月營收 YoY ${formatPct(revenueGrowth)}，累計 YoY ${formatPct(cumulativeRevenueGrowth)}`,
        value: formatPct(revenueGrowth),
        pulseValue: revenueGrowth,
        direction: revenueGrowth,
        tone: rowTone(revenueGrowth),
      },
      {
        title: "獲利品質",
        description: `EPS ${formatIndicatorValue(eps)}，ROE ${formatRatioPct(roe)}`,
        value: formatIndicatorValue(eps),
        pulseValue: eps,
        direction: eps,
        tone: rowTone(eps),
      },
      {
        title: "長期籌碼",
        description: `${largeHolderLots}張以上持股比 ${formatRatioPct(largeHolder.ratio)}，最新 ${formatDate(largeHolder.dataDate)}`,
        value: formatPct(largeHolder.change),
        pulseValue: largeHolder.change,
        direction: largeHolder.change,
        tone: rowTone(largeHolder.change),
      }
    );

    if (finiteNumber(monthlyMa6) && finiteNumber(monthlyMa12)) addBadge(monthlyMa6 >= monthlyMa12 ? "月線偏多" : "月線偏弱", monthlyMa6 >= monthlyMa12 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
    if (finiteNumber(revenueGrowth)) addBadge(revenueGrowth >= 0 ? "營收成長" : "營收衰退", revenueGrowth >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
    if (finiteNumber(monthStats12.rangePositionPct) && monthStats12.rangePositionPct >= 80) addBadge("接近12月高位", "text-omi-warning bg-omi-warning-soft");

    return {
      title: titleFor("長線偏多", "長線觀察", "長線偏弱"),
      summary: summaryFrom([
        finiteNumber(monthStats12.changePct) ? `12月${monthStats12.changePct >= 0 ? "走升" : "走弱"}` : "資料不足",
        finiteNumber(revenueGrowth) ? (revenueGrowth >= 0 ? "營收成長" : "營收衰退") : "營收待讀取",
        finiteNumber(largeHolder.change) ? (largeHolder.change >= 0 ? "大戶增加" : "大戶減少") : "籌碼待讀取",
      ]),
      value: monthStats6.changePct ?? monthStats12.changePct,
      valueLabel: monthStats6.changePct !== null ? "近6月" : "近12月",
      score,
      rows,
      badges,
    };
}

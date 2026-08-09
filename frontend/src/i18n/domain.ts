import type { TranslationFunction, TranslationValues } from "./messages";

function translatedValue(
  t: TranslationFunction,
  key: string,
  fallback: string | null | undefined,
  values?: TranslationValues
) {
  const value = t(key, values);
  return value === key ? fallback ?? "" : value;
}

export function marketLabel(t: TranslationFunction, market: string) {
  if (market === "crypto") return "Crypto";
  return t(`markets.${market}.label`);
}

export function marketSummary(t: TranslationFunction, market: string) {
  if (market === "crypto") return "Quotes / depth / funding / Taiwan spread";
  return t(`markets.${market}.summary`);
}

export function rankByLabel(t: TranslationFunction, rankBy: string) {
  if (rankBy === "none" || rankBy === "watchlist") return t("rank.none");
  if (rankBy === "change_pct") return t("rank.changePct");
  if (rankBy === "score") return t("rank.score");
  if (rankBy === "volume") return t("rank.volume");
  if (rankBy === "foreign_net") return t("rank.foreignNet");
  if (rankBy === "margin_balance_change_pct") return t("rank.marginBalanceChangePct");
  if (rankBy === "close") return t("rank.close");
  return rankBy;
}

export function trendDirectionLabel(
  t: TranslationFunction,
  value: number | null | undefined
) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (value > 0) return t("trend.up");
  if (value < 0) return t("trend.down");
  return t("trend.flat");
}

export function rowStatusLabel(t: TranslationFunction, status: string) {
  if (status === "intraday") return t("statusLabels.intraday");
  if (status === "ready") return t("statusLabels.ready");
  if (status === "no_data") return t("statusLabels.noData");
  if (status === "error") return t("statusLabels.error");
  if (status.includes("bullish")) return t("statusLabels.bullish");
  if (status.includes("bearish")) return t("statusLabels.bearish");
  return status || "-";
}

export function usAssetTypeLabel(
  t: TranslationFunction,
  assetType: string | null | undefined
) {
  if (!assetType) return "-";

  const normalized = assetType.toLowerCase();
  if (normalized === "stock") return t("usStockDetail.assetTypes.stock");
  if (normalized === "index") return t("usStockDetail.assetTypes.index");
  if (normalized === "etf") return t("usStockDetail.assetTypes.etf");
  return assetType;
}

export function timeframeLabel(t: TranslationFunction, timeframe: string) {
  return t(`timeframes.${timeframe}`);
}

const RADAR_SIGNAL_KEY_BY_LABEL: Record<string, string> = {
  上漲: "price_up",
  下跌: "price_down",
  "站在 MA20 之上": "above_ma20",
  "跌破 MA20": "below_ma20",
  "MA5 高於 MA20": "ma5_above_ma20",
  "MA5 低於 MA20": "ma5_below_ma20",
  "MA20 高於 MA60": "ma20_above_ma60",
  "MA20 低於 MA60": "ma20_below_ma60",
  "重新站上 MA20": "cross_above_ma20",
  "EMA 快線高於慢線": "ema_fast_above_slow",
  "EMA 快線低於慢線": "ema_fast_below_slow",
  "EMA 黃金交叉": "ema_bullish_cross",
  "EMA 死亡交叉": "ema_bearish_cross",
  "MACD 偏多": "macd_positive",
  "MACD 偏空": "macd_negative",
  "ADX 多方趨勢": "adx_bull_trend",
  "ADX 空方趨勢": "adx_bear_trend",
  "突破 20 日高": "donchian_breakout",
  "跌破 20 日低": "donchian_breakdown",
  "RSI 多方區": "rsi_bull_zone",
  "RSI 偏弱": "rsi_weak",
  "RSI 過熱": "rsi_overheated",
  "MFI 資金流入": "mfi_inflow",
  "MFI 偏弱": "mfi_outflow",
  "ROC 正動能": "roc_positive",
  "ROC 負動能": "roc_negative",
  "量增價漲": "volume_price_up",
  "量增價跌": "volume_price_down",
  "量能放大": "volume_expansion",
  "成交量高於 5 日均量": "volume_above_ma5",
  "跌破 20 日支撐": "structure_support_break",
  "突破 20 日壓力": "structure_resistance_breakout",
  "貼近 20 日支撐": "near_support",
  "貼近 20 日壓力": "near_resistance",
  突破布林上緣: "bollinger_breakout",
  跌破布林下緣: "bollinger_breakdown",
  布林壓縮: "bollinger_squeeze",
  "KD 黃金交叉": "kd_bullish_cross",
  "KD 死亡交叉": "kd_bearish_cross",
  "KD 過熱": "kd_overbought",
  "KD 低檔": "kd_oversold",
  "ATR 高波動": "atr_high_volatility",
  "ATR 波動擴大": "atr_expanding",
};

const RADAR_CONTEXT_SOURCE_KEY_BY_SIGNAL_KEY: Record<string, string> = {
  intraday_trend: "intraday",
  institutional_net: "chipFlow",
  margin_balance_change: "margin",
  short_balance_change: "short",
  revenue_yoy: "revenue",
  financial_quality: "financial",
  cross_market_context: "crossMarket",
};

const RADAR_CONTEXT_LABEL_KEY_BY_LABEL: Record<string, string> = {
  法人確認: "institutionalConfirm",
  法人背離: "institutionalDivergence",
  法人逆勢買: "institutionalContrarianBuy",
  法人偏多: "institutionalBullish",
  法人偏空: "institutionalBearish",
  融資過熱: "marginOverheated",
  融資跟進: "marginFollow",
  融資撐盤: "marginSupport",
  融資升溫: "marginWarming",
  融資降溫: "marginCooling",
  融資退場: "marginExit",
  融資減少: "marginReduced",
  融券加壓: "shortPressure",
  空方加壓: "shortSidePressure",
  融券增加: "shortIncrease",
  回補助攻: "shortCoverSupport",
  空方回補: "shortCover",
  融券回補: "shortReduced",
  盤中續強: "intradayStrong",
  盤中轉弱: "intradayWeakening",
  盤中續弱: "intradayContinuedWeak",
  盤中反彈: "intradayRebound",
  盤中偏多: "intradayBullish",
  盤中偏空: "intradayBearish",
  營收背書: "revenueSupport",
  營收逆勢強: "revenueContrarianStrong",
  營收成長: "revenueGrowth",
  營收背離: "revenueDivergence",
  營收同弱: "revenueWeakTogether",
  營收衰退: "revenueDecline",
  獲利背離: "profitDivergence",
  獲利同弱: "profitWeakTogether",
  獲利拖累: "profitDrag",
  獲利背書: "profitSupport",
  獲利逆勢強: "profitContrarianStrong",
  獲利穩定: "profitStable",
  外部順風: "externalTailwind",
  外部弱勢確認: "externalWeaknessConfirm",
  外部逆風: "externalHeadwind",
  跨市場中性: "crossMarketNeutral",
  外部脈絡受限: "crossMarketLimited",
};

export function radarBucketLabel(
  t: TranslationFunction,
  bucket: string,
  fallback: string
) {
  return translatedValue(t, `radar.buckets.${bucket}.label`, fallback);
}

export function radarBucketDescription(
  t: TranslationFunction,
  bucket: string,
  fallback: string
) {
  return translatedValue(t, `radar.buckets.${bucket}.description`, fallback);
}

export function radarTechnicalGradeLabel(
  t: TranslationFunction,
  grade: string,
  fallback: string
) {
  return translatedValue(t, `radar.technicalGrades.${grade}.label`, fallback);
}

export function radarTechnicalGradeDescription(
  t: TranslationFunction,
  grade: string,
  fallback: string
) {
  return translatedValue(t, `radar.technicalGrades.${grade}.description`, fallback);
}

export function radarSignalLabel(
  t: TranslationFunction,
  signalKey: string | null | undefined,
  fallback: string | null | undefined
) {
  if (!signalKey) return fallback ?? "";
  return translatedValue(t, `radar.signals.${signalKey}`, fallback ?? signalKey);
}

export function radarSignalLabelFromText(
  t: TranslationFunction,
  label: string | null | undefined
) {
  if (!label) return "";
  return radarSignalLabel(t, RADAR_SIGNAL_KEY_BY_LABEL[label], label);
}

export function radarSetupLabel(
  t: TranslationFunction,
  bucket: string,
  fallback: string
) {
  return translatedValue(t, `radar.setup.${bucket}`, fallback);
}

export function radarTimingLabel(
  t: TranslationFunction,
  bucket: string,
  fallback: string
) {
  return translatedValue(t, `radar.timing.${bucket}`, fallback);
}

export function radarRiskLabel(
  t: TranslationFunction,
  bucket: string,
  fallback: string
) {
  return translatedValue(t, `radar.risk.${bucket}`, fallback);
}

export function radarPriceLevelLabel(
  t: TranslationFunction,
  label: string,
  fallback: string
) {
  const key = ({
    回收壓力: "reclaimResistance",
    突破壓力: "breakoutResistance",
    失效支撐: "invalidationSupport",
    reclaimResistance: "reclaimResistance",
    breakoutResistance: "breakoutResistance",
    invalidationSupport: "invalidationSupport",
  } satisfies Record<string, string>)[label];

  return key ? translatedValue(t, `radar.priceLevels.${key}`, fallback) : fallback;
}

export function radarActionLabel(
  t: TranslationFunction,
  bucket: string,
  fallback: string,
  stale: boolean
) {
  const base = translatedValue(t, `radar.actions.${bucket}`, fallback);
  return stale ? t("radar.actions.staleSuffix", { action: base }) : base;
}

export function radarContextSourceLabel(
  t: TranslationFunction,
  signalKey: string,
  fallback: string
) {
  const sourceKey = RADAR_CONTEXT_SOURCE_KEY_BY_SIGNAL_KEY[signalKey];
  return sourceKey
    ? translatedValue(t, `radar.contextSources.${sourceKey}`, fallback)
    : fallback;
}

export function radarContextSignalLabel(
  t: TranslationFunction,
  label: string
) {
  const labelKey = RADAR_CONTEXT_LABEL_KEY_BY_LABEL[label];
  return labelKey
    ? translatedValue(t, `radar.contextLabels.${labelKey}`, label)
    : label;
}

export function radarContextValueLabel(
  t: TranslationFunction,
  valueLabel: string | null | undefined
) {
  if (!valueLabel) return "";
  return valueLabel.replace(/張/g, t("radar.units.lots"));
}

export function radarContextDescription(
  t: TranslationFunction,
  signalKey: string,
  fallback: string,
  valueLabel: string | null | undefined
) {
  const value = radarContextValueLabel(t, valueLabel);
  return translatedValue(t, `radar.contextDescriptions.${signalKey}`, fallback, {
    value,
  });
}

"use client";

import { StateSurface } from "@/components/LoadingPlaceholders";
import { WatchlistRadarV2OutcomePanel } from "@/components/WatchlistRadarV2OutcomePanel";
import type {
  WatchlistGroupRadarRead,
  WatchlistRadarBucketRead,
  WatchlistRadarItemRead,
  WatchlistRadarMode,
  WatchlistRadarOutcomeItemRead,
  WatchlistRadarOutcomeSummaryRead,
  WatchlistRadarV2OutcomeSummaryRead,
} from "@/types/market";
import {
  radarActionLabel,
  radarBucketDescription,
  radarBucketLabel,
  radarContextDescription,
  radarContextSignalLabel,
  radarContextSourceLabel,
  radarPriceLevelLabel,
  radarRiskLabel,
  radarSetupLabel,
  radarSignalLabel,
  radarSignalLabelFromText,
  radarTechnicalGradeDescription,
  radarTechnicalGradeLabel,
  radarTimingLabel,
  useT,
  type TranslationFunction,
} from "@/i18n";

type LoadState = "idle" | "loading" | "success" | "error";

type WatchlistRadarPanelProps = {
  radar: WatchlistGroupRadarRead | null;
  loadState: LoadState;
  mode: WatchlistRadarMode;
  selectedStockId: string | null;
  disabled?: boolean;
  scopeLabel?: string | null;
  notice?: string | null;
  outcomeSummary?: WatchlistRadarOutcomeSummaryRead | null;
  outcomeLoadState?: LoadState;
  outcomeHistory?: WatchlistRadarOutcomeSummaryRead[];
  outcomeHistoryOpen?: boolean;
  outcomeHistoryLoadState?: LoadState;
  outcomeDetailLoadState?: LoadState;
  selectedOutcomeSnapshotId?: number | null;
  getModeHref?: (mode: WatchlistRadarMode) => string;
  onModeChange: (mode: WatchlistRadarMode) => void;
  onReload: () => void;
  onOpenOutcomeHistory?: () => void;
  onCloseOutcomeHistory?: () => void;
  onReloadOutcomeHistory?: () => void;
  onSelectOutcomeSnapshot?: (snapshotId: number) => void;
  onEvaluateOutcomeSnapshot?: (snapshotId: number) => void;
  v2OutcomeHistory?: WatchlistRadarV2OutcomeSummaryRead[];
  v2OutcomeHistoryOpen?: boolean;
  v2OutcomeHistoryLoadState?: LoadState;
  v2OutcomeDetailLoadState?: LoadState;
  selectedV2OutcomeSnapshotDate?: string | null;
  onOpenV2OutcomeHistory?: () => void;
  onCloseV2OutcomeHistory?: () => void;
  onReloadV2OutcomeHistory?: () => void;
  onSelectV2OutcomeSnapshot?: (snapshotDate: string) => void;
  onSelectStock: (stockId: string, stockName: string | null) => void;
};

type RadarBucketGroupKey =
  | "price"
  | "volatility"
  | "structure"
  | "volume"
  | "momentum"
  | "other";

const RADAR_BUCKET_GROUPS: Array<{
  key: RadarBucketGroupKey;
  labelKey: string;
}> = [
  { key: "price", labelKey: "radar.bucketGroups.price" },
  { key: "volatility", labelKey: "radar.bucketGroups.volatility" },
  { key: "structure", labelKey: "radar.bucketGroups.structure" },
  { key: "volume", labelKey: "radar.bucketGroups.volume" },
  { key: "momentum", labelKey: "radar.bucketGroups.momentum" },
  { key: "other", labelKey: "radar.bucketGroups.other" },
];

const RADAR_BUCKET_GROUP_BY_KEY: Record<string, RadarBucketGroupKey> = {
  limit_up_lock: "price",
  surge_up: "price",
  limit_down_liquidity: "price",
  selloff_risk: "price",
  limit_up_move: "price",
  limit_down_move: "price",
  overheated: "volatility",
  volatility_risk: "volatility",
  support_break: "structure",
  breakout_high: "structure",
  trend_reclaim: "structure",
  breakout: "structure",
  compression_watch: "structure",
  pullback: "structure",
  volume_up: "volume",
  volume: "volume",
  volume_down: "volume",
  momentum: "momentum",
  bearish_momentum: "momentum",
};

const RADAR_MODE_OPTIONS: Array<{
  value: WatchlistRadarMode;
  labelKey: string;
  titleKey: string;
}> = [
  {
    value: "action",
    labelKey: "radar.modes.action",
    titleKey: "radar.modeDescriptions.action",
  },
  {
    value: "surge",
    labelKey: "radar.modes.surge",
    titleKey: "radar.modeDescriptions.surge",
  },
  {
    value: "breakout",
    labelKey: "radar.modes.breakout",
    titleKey: "radar.modeDescriptions.breakout",
  },
  {
    value: "overheat",
    labelKey: "radar.modes.overheat",
    titleKey: "radar.modeDescriptions.overheat",
  },
  {
    value: "risk",
    labelKey: "radar.modes.risk",
    titleKey: "radar.modeDescriptions.risk",
  },
  {
    value: "momentum",
    labelKey: "radar.modes.momentum",
    titleKey: "radar.modeDescriptions.momentum",
  },
];

function formatRadarDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function formatRadarPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatRadarPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function outcomeStatusText(
  t: TranslationFunction,
  summary: WatchlistRadarOutcomeSummaryRead | null | undefined
) {
  if (!summary || summary.status === "no_snapshot") {
    return t("radar.outcome.noSnapshot");
  }

  const date = formatRadarDate(summary.snapshot?.snapshot_date);

  if (summary.status === "not_evaluated") {
    return t("radar.outcome.notEvaluated", { date });
  }

  if (summary.status === "pending") {
    return t("radar.outcome.pending", {
      date,
      count: summary.pending_count,
    });
  }

  return t("radar.outcome.evaluated", {
    date,
    count: summary.total_count,
  });
}

function outcomeStatusClass(status: string | null | undefined) {
  if (status === "evaluated" || status === "hit") {
    return "border-omi-success-border bg-omi-success-soft text-omi-success";
  }
  if (status === "miss") {
    return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  }
  if (status === "pending") return "border-omi-warning-border bg-omi-warning-soft text-omi-warning";
  if (status === "not_evaluated") return "border-omi-info-border bg-omi-info-soft text-omi-info-strong";
  return "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-muted";
}

function outcomeStatusLabel(t: TranslationFunction, status: string | null | undefined) {
  const normalizedStatus = status === "no_snapshot" ? "noSnapshot" : status || "noSnapshot";
  const key = `radar.outcome.status.${normalizedStatus}`;
  const label = t(key);
  return label === key ? status || "-" : label;
}

function outcomeSavedCount(summary: WatchlistRadarOutcomeSummaryRead | null | undefined) {
  return summary?.snapshot?.radar_count ?? summary?.total_count ?? 0;
}

function outcomeMetricClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-omi-text-muted";
  }
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text";
}

function outcomeReviewDetails(
  item: WatchlistRadarOutcomeItemRead,
  t: TranslationFunction
) {
  return [
    item.outcome_trade_date
      ? `${t("radar.outcome.detailLabels.tradeDate")}：${formatRadarDate(
          item.outcome_trade_date
        )}`
      : null,
    item.signal_close_price !== null
      ? `${t("radar.outcome.detailLabels.signalClose")}：${formatRadarPrice(
          item.signal_close_price
        )}`
      : null,
    item.outcome_open_price !== null
      ? `${t("radar.outcome.detailLabels.outcomeOpen")}：${formatRadarPrice(
          item.outcome_open_price
        )}`
      : null,
    item.outcome_high_price !== null
      ? `${t("radar.outcome.detailLabels.outcomeHigh")}：${formatRadarPrice(
          item.outcome_high_price
        )}`
      : null,
    item.outcome_low_price !== null
      ? `${t("radar.outcome.detailLabels.outcomeLow")}：${formatRadarPrice(
          item.outcome_low_price
        )}`
      : null,
    item.outcome_close_price !== null
      ? `${t("radar.outcome.detailLabels.outcomeClose")}：${formatRadarPrice(
          item.outcome_close_price
        )}`
      : null,
    item.open_gap_pct !== null
      ? `${t("radar.outcome.detailLabels.openGap")}：${formatRadarPct(
          item.open_gap_pct
        )}`
      : null,
    item.close_return_pct !== null
      ? `${t("radar.outcome.detailLabels.closeReturn")}：${formatRadarPct(
          item.close_return_pct
        )}`
      : null,
    item.max_favorable_pct !== null
      ? `${t("radar.outcome.detailLabels.maxFavorable")}：${formatRadarPct(
          item.max_favorable_pct
        )}`
      : null,
    item.max_adverse_pct !== null
      ? `${t("radar.outcome.detailLabels.maxAdverse")}：${formatRadarPct(
          item.max_adverse_pct
        )}`
      : null,
    item.intraday_range_pct !== null
      ? `${t("radar.outcome.detailLabels.intradayRange")}：${formatRadarPct(
          item.intraday_range_pct
        )}`
      : null,
    item.volume_change_pct !== null
      ? `${t("radar.outcome.detailLabels.volumeChange")}：${formatRadarPct(
          item.volume_change_pct
        )}`
      : null,
    item.reason
      ? `${t("radar.outcome.detailLabels.reason")}：${item.reason}`
      : null,
  ].filter((detail): detail is string => Boolean(detail));
}

function formatDistanceFromClose(
  level: number | null | undefined,
  close: number | null | undefined
) {
  if (
    level === null ||
    level === undefined ||
    close === null ||
    close === undefined ||
    Number.isNaN(level) ||
    Number.isNaN(close) ||
    close === 0
  ) {
    return null;
  }

  return formatRadarPct(((level - close) / close) * 100);
}

function formatRadarNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function formatSignedRadarNumber(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const formatted = value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
  return value > 0 ? `+${formatted}` : formatted;
}

function priceLevelNumber(item: WatchlistRadarItemRead, key: string) {
  const value = item.price_levels?.[key];
  return typeof value === "number" && !Number.isNaN(value) ? value : null;
}

function indicatorNumber(item: WatchlistRadarItemRead, group: string, key: string) {
  const value = item.indicator_snapshot?.[group]?.[key];
  return typeof value === "number" && !Number.isNaN(value) ? value : null;
}

function withDetailTone(value: string, tone: string | null) {
  return tone ? `${value} (${tone})` : value;
}

function detailTone(t: TranslationFunction, key: string) {
  return t(`radar.detailTones.${key}`);
}

function rsiTone(t: TranslationFunction, value: number) {
  if (value >= 70) return detailTone(t, "rsiHot");
  if (value >= 55) return detailTone(t, "rsiBull");
  if (value >= 40) return detailTone(t, "rsiNeutral");
  return detailTone(t, "rsiWeak");
}

function adxTone(t: TranslationFunction, value: number) {
  if (value >= 35) return detailTone(t, "adxStrong");
  if (value >= 25) return detailTone(t, "adxBuilding");
  return detailTone(t, "adxWeak");
}

function mfiTone(t: TranslationFunction, value: number) {
  if (value >= 80) return detailTone(t, "mfiHot");
  if (value >= 60) return detailTone(t, "mfiInflow");
  if (value >= 40) return detailTone(t, "mfiNeutral");
  return detailTone(t, "mfiOutflow");
}

function macdTone(t: TranslationFunction, value: number) {
  if (Math.abs(value) < 0.01) return detailTone(t, "macdNeutral");
  return value > 0 ? detailTone(t, "macdPositive") : detailTone(t, "macdNegative");
}

function rocTone(t: TranslationFunction, value: number) {
  if (Math.abs(value) < 0.01) return detailTone(t, "rocNeutral");
  return value > 0 ? detailTone(t, "rocPositive") : detailTone(t, "rocNegative");
}

function atrTone(t: TranslationFunction, value: number) {
  if (value >= 8) return detailTone(t, "atrHigh");
  if (value >= 4) return detailTone(t, "atrNormal");
  return detailTone(t, "atrLow");
}

function kdTone(
  t: TranslationFunction,
  kValue: number | null,
  dValue: number | null
) {
  if (kValue === null || dValue === null) return null;
  if (kValue >= 80 && dValue >= 80) return detailTone(t, "kdOverbought");
  if (kValue <= 20 && dValue <= 20) return detailTone(t, "kdOversold");
  return kValue >= dValue ? detailTone(t, "kdBullish") : detailTone(t, "kdBearish");
}

function bollingerTone(
  t: TranslationFunction,
  close: number | null | undefined,
  upper: number | null,
  lower: number | null
) {
  if (
    close === null ||
    close === undefined ||
    upper === null ||
    lower === null ||
    Number.isNaN(close)
  ) {
    return null;
  }

  const width = upper - lower;
  if (width <= 0) return null;

  const position = (close - lower) / width;
  if (position >= 0.8) return detailTone(t, "bollingerNearUpper");
  if (position <= 0.2) return detailTone(t, "bollingerNearLower");
  return detailTone(t, "bollingerMiddle");
}

function radarValueTone(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-omi-text-muted";
  }

  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text";
}

function urgencyClass(value: string) {
  if (value === "high") return "omi-signal-chip-positive";
  if (value === "medium") return "omi-signal-chip-warning";
  return "omi-signal-chip-neutral";
}

function technicalGradeClass(value: string) {
  if (value === "strong") return "omi-signal-chip-positive";
  if (value === "medium") return "omi-signal-chip-info";
  return "omi-signal-chip-neutral";
}

function contextSignalClass(tone: string, stance: string) {
  if (stance === "contradict" || tone === "warning") {
    return "omi-signal-chip-warning";
  }

  if (tone === "positive") return "omi-signal-chip-positive";
  if (tone === "negative") return "omi-signal-chip-negative";
  return "omi-signal-chip-neutral";
}

function bucketClass(bucket: string) {
  if (
    bucket === "limit_up_lock" ||
    bucket === "surge_up" ||
    bucket === "limit_up_move" ||
    bucket === "breakout_high" ||
    bucket === "trend_reclaim" ||
    bucket === "volume_up" ||
    bucket === "momentum"
  ) {
    return "omi-signal-chip-positive";
  }

  if (
    bucket === "risk" ||
    bucket === "limit_down_liquidity" ||
    bucket === "selloff_risk" ||
    bucket === "limit_down_move" ||
    bucket === "support_break" ||
    bucket === "volume_down" ||
    bucket === "bearish_momentum"
  ) {
    return "omi-signal-chip-negative";
  }

  if (bucket === "overheated") {
    return "omi-signal-chip-warning";
  }

  if (bucket === "volatility_risk") {
    return "omi-signal-chip-heat";
  }

  if (
    bucket === "breakout" ||
    bucket === "pullback" ||
    bucket === "compression_watch"
  ) {
    return "omi-signal-chip-info";
  }

  if (bucket === "volume") {
    return "omi-signal-chip-warning";
  }

  return "omi-signal-chip-neutral";
}

function groupedRadarBuckets(buckets: WatchlistRadarBucketRead[]) {
  const bucketsByGroup = new Map<RadarBucketGroupKey, WatchlistRadarBucketRead[]>();

  for (const group of RADAR_BUCKET_GROUPS) {
    bucketsByGroup.set(group.key, []);
  }

  for (const bucket of buckets) {
    const groupKey = RADAR_BUCKET_GROUP_BY_KEY[bucket.key] ?? "other";
    bucketsByGroup.get(groupKey)?.push(bucket);
  }

  return RADAR_BUCKET_GROUPS.map((group) => ({
    ...group,
    buckets: bucketsByGroup.get(group.key) ?? [],
  })).filter((group) => group.buckets.length > 0);
}

function itemMeta(item: WatchlistRadarItemRead, t: TranslationFunction) {
  const bucketLabel = radarBucketLabel(t, item.bucket, item.bucket_label);

  return [
    bucketLabel,
    item.stale ? t("radar.staleItem") : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function technicalSignalDetails(item: WatchlistRadarItemRead, t: TranslationFunction) {
  const bucketLabel = radarBucketLabel(t, item.bucket, item.bucket_label);
  const signalKeys = Array.from(
    new Set(
      [
        ...item.matched_signal_keys,
        item.primary_signal_key,
        ...item.signal_keys,
      ].filter((key): key is string => Boolean(key))
    )
  );
  const technicalLabels = [
    ...signalKeys.map((key) => radarSignalLabel(t, key, key)),
    ...item.technical_notes.map((label) => radarSignalLabelFromText(t, label)),
    ...item.matched_signal_labels.map((label) =>
      radarSignalLabelFromText(t, label)
    ),
    item.primary_signal_label
      ? radarSignalLabelFromText(t, item.primary_signal_label)
      : null,
    ...item.signal_labels.map((label) => radarSignalLabelFromText(t, label)),
  ].filter(
    (label): label is string =>
      Boolean(label) && label !== bucketLabel && label !== item.bucket_label
  );

  return Array.from(new Set(technicalLabels)).slice(0, 6);
}

function factorScoreDetails(item: WatchlistRadarItemRead, t: TranslationFunction) {
  const entries: Array<[string, string]> = [
    ["trend", t("radar.factors.trend")],
    ["momentum", t("radar.factors.momentum")],
    ["volume", t("radar.factors.volume")],
    ["structure", t("radar.factors.structure")],
    ["volatility", t("radar.factors.volatility")],
  ];

  return entries
    .map(([key, label]) => {
      const value = item.factor_scores?.[key];
      const formatted = formatSignedRadarNumber(
        typeof value === "number" && !Number.isNaN(value) ? value : null,
        1
      );
      return formatted ? `${label} ${formatted}` : null;
    })
    .filter((value): value is string => Boolean(value));
}

function radarV2Label(
  t: TranslationFunction,
  namespace: "directions" | "grades" | "regimes",
  value: string
) {
  const key = `radar.v2.${namespace}.${value}`;
  const translated = t(key);
  return translated === key ? value.replaceAll("_", " ") : translated;
}

function radarV2DirectionClass(direction: number) {
  if (direction > 0) {
    return "border-omi-success-border bg-omi-success-soft text-omi-success";
  }
  if (direction < 0) {
    return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  }
  return "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-muted";
}

function radarV2Details(item: WatchlistRadarItemRead, t: TranslationFunction) {
  const evaluation = item.radar_v2;
  if (!evaluation) return [];

  const directionKey =
    evaluation.direction > 0
      ? "bullish"
      : evaluation.direction < 0
        ? "bearish"
        : "neutral";
  const topFamilies = Object.entries(evaluation.family_scores)
    .map(([family, values]) => {
      const rawValue = values.direction_score;
      const value =
        typeof rawValue === "number" && !Number.isNaN(rawValue)
          ? formatSignedRadarNumber(rawValue, 1)
          : null;
      return value
        ? `${radarV2Label(t, "regimes", family)} ${value}`
        : null;
    })
    .filter((value): value is string => Boolean(value))
    .slice(0, 4);

  return [
    `${t("radar.v2.fields.direction")} ${radarV2Label(
      t,
      "directions",
      directionKey
    )} ${formatSignedRadarNumber(evaluation.direction_score, 1) ?? "0"}`,
    `${t("radar.v2.fields.evidence")} ${evaluation.evidence_score.toFixed(1)}`,
    `${t("radar.v2.fields.confidence")} ${evaluation.confidence_score.toFixed(1)}`,
    `${t("radar.v2.fields.conflict")} ${evaluation.conflict_score.toFixed(1)}`,
    `${t("radar.v2.fields.risk")} ${evaluation.risk_score.toFixed(1)}`,
    `${t("radar.v2.fields.instrumentRegime")} ${radarV2Label(
      t,
      "regimes",
      evaluation.instrument_regime
    )}`,
    `${t("radar.v2.fields.marketRegime")} ${radarV2Label(
      t,
      "regimes",
      evaluation.market_regime
    )}`,
    ...topFamilies,
  ];
}

function priceLevelDetails(item: WatchlistRadarItemRead, t: TranslationFunction) {
  const levelDetail = (label: string, key: string) => {
    const value = priceLevelNumber(item, key);
    const formatted = formatRadarNumber(value);
    if (!formatted) return null;

    const distance = formatDistanceFromClose(value, item.close);
    const distanceText = distance
      ? t("radar.detailFields.distanceFromClose", { value: distance })
      : null;

    return withDetailTone(`${label} ${formatted}`, distanceText);
  };

  const atrValue = priceLevelNumber(item, "atr_pct");
  const atrPct = formatRadarPct(atrValue);
  const supportBroken = item.price_levels?.support_broken === true;

  return [
    levelDetail(
      t(
        supportBroken
          ? "radar.detailFields.brokenSupport"
          : "radar.detailFields.support"
      ),
      "support"
    ),
    levelDetail(t("radar.detailFields.resistance"), "resistance"),
    levelDetail(t("radar.detailFields.previousClose"), "previous_close"),
    levelDetail(t("radar.detailFields.ma20"), "ma20"),
    levelDetail(t("radar.detailFields.ma60"), "ma60"),
    atrPct !== "-" && atrValue !== null
      ? withDetailTone(`${t("radar.detailFields.atrPct")} ${atrPct}`, atrTone(t, atrValue))
      : null,
  ]
    .filter((value): value is string => Boolean(value));
}

function indicatorDetails(item: WatchlistRadarItemRead, t: TranslationFunction) {
  const ma5Value = indicatorNumber(item, "ma", "ma5");
  const ma20Value = indicatorNumber(item, "ma", "ma20");
  const ma60Value = indicatorNumber(item, "ma", "ma60");
  const kdKValue = indicatorNumber(item, "kd", "k9");
  const kdDValue = indicatorNumber(item, "kd", "d9");
  const bollingerUpperValue = indicatorNumber(item, "bollinger", "upper20");
  const bollingerLowerValue = indicatorNumber(item, "bollinger", "lower20");
  const ma5 = formatRadarNumber(ma5Value);
  const ma20 = formatRadarNumber(ma20Value);
  const ma60 = formatRadarNumber(ma60Value);
  const kdK = formatRadarNumber(kdKValue, 1);
  const kdD = formatRadarNumber(kdDValue, 1);
  const bollingerUpper = formatRadarNumber(bollingerUpperValue);
  const bollingerLower = formatRadarNumber(bollingerLowerValue);
  const maTones = [
    ma5Value !== null && ma20Value !== null
      ? ma5Value >= ma20Value
        ? detailTone(t, "ma5AboveMa20")
        : detailTone(t, "ma5BelowMa20")
      : null,
    ma20Value !== null && ma60Value !== null
      ? ma20Value >= ma60Value
        ? detailTone(t, "ma20AboveMa60")
        : detailTone(t, "ma20BelowMa60")
      : null,
  ].filter(Boolean);

  const details = [
    ma5 || ma20 || ma60
      ? withDetailTone(
          `MA ${[
            ma5 ? `5 ${ma5}` : null,
            ma20 ? `20 ${ma20}` : null,
            ma60 ? `60 ${ma60}` : null,
          ]
            .filter(Boolean)
            .join(" / ")}`,
          maTones.join("; ") || null
        )
      : null,
    (() => {
      const rawValue = indicatorNumber(item, "macd", "histogram");
      const value = formatSignedRadarNumber(rawValue, 2);
      return value && rawValue !== null
        ? withDetailTone(
            `${t("radar.detailFields.macdHistogram")} ${value}`,
            macdTone(t, rawValue)
          )
        : null;
    })(),
    (() => {
      const rawValue = indicatorNumber(item, "rsi", "rsi14");
      const value = formatRadarNumber(rawValue, 1);
      return value && rawValue !== null
        ? withDetailTone(`RSI14 ${value}`, rsiTone(t, rawValue))
        : null;
    })(),
    (() => {
      const rawValue = indicatorNumber(item, "adx", "adx14");
      const value = formatRadarNumber(rawValue, 1);
      return value && rawValue !== null
        ? withDetailTone(`ADX14 ${value}`, adxTone(t, rawValue))
        : null;
    })(),
    (() => {
      const rawValue = indicatorNumber(item, "mfi", "mfi14");
      const value = formatRadarNumber(rawValue, 1);
      return value && rawValue !== null
        ? withDetailTone(`MFI14 ${value}`, mfiTone(t, rawValue))
        : null;
    })(),
    (() => {
      const rawValue = indicatorNumber(item, "roc", "roc12");
      const value = formatSignedRadarNumber(rawValue, 2);
      return value && rawValue !== null
        ? withDetailTone(`ROC12 ${value}%`, rocTone(t, rawValue))
        : null;
    })(),
    kdK || kdD
      ? withDetailTone(
          `KD ${[kdK, kdD].filter(Boolean).join(" / ")}`,
          kdTone(t, kdKValue, kdDValue)
        )
      : null,
    bollingerUpper || bollingerLower
      ? withDetailTone(
          `${t("radar.detailFields.bollinger")} ${[
            bollingerUpper ? `${t("radar.detailFields.upper")} ${bollingerUpper}` : null,
            bollingerLower ? `${t("radar.detailFields.lower")} ${bollingerLower}` : null,
          ]
            .filter(Boolean)
            .join(" / ")}`,
          bollingerTone(t, item.close, bollingerUpperValue, bollingerLowerValue)
        )
      : null,
  ];

  return details.filter((value): value is string => Boolean(value)).slice(0, 8);
}

function keyLevelText(item: WatchlistRadarItemRead, t: TranslationFunction) {
  const label = item.price_levels.key_level_label;
  const value = item.price_levels.key_level;

  if (typeof label !== "string" || typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }

  return `${radarPriceLevelLabel(t, label, label)} ${formatRadarPrice(value)}`;
}

function scanLine(item: WatchlistRadarItemRead, t: TranslationFunction) {
  const bucketLabel = radarBucketLabel(t, item.bucket, item.bucket_label);
  const backendOwnedV2 =
    item.radar_v2?.rule_version === "radar_v2.0";

  return [
    backendOwnedV2
      ? item.setup_label || bucketLabel
      : item.setup_label
      ? radarSetupLabel(t, item.bucket, item.setup_label)
      : bucketLabel,
    backendOwnedV2
      ? item.timing_label
      : item.timing_label
        ? radarTimingLabel(t, item.bucket, item.timing_label)
        : null,
    backendOwnedV2
      ? item.risk_label
      : item.risk_label
        ? radarRiskLabel(t, item.bucket, item.risk_label)
        : null,
    keyLevelText(item, t),
  ]
    .filter(Boolean)
    .join(" · ");
}

function contextSignals(item: WatchlistRadarItemRead) {
  return (item.context_signals ?? []).slice(0, 3);
}

function urgencyLabel(t: TranslationFunction, urgency: string) {
  const key = `radar.urgency.${urgency}`;
  const label = t(key);
  return label === key ? urgency : label;
}

function signalBadge(
  label: string,
  value: string,
  className: string,
  title?: string
) {
  return (
    <span
      className={[
        "omi-signal-chip inline-flex shrink-0 items-center gap-1 border px-1.5 py-0.5 text-[11px] font-semibold",
        className,
      ].join(" ")}
      title={title}
    >
      <span className="text-[10px] opacity-75">{label}：</span>
      <span className="truncate">{value}</span>
    </span>
  );
}

function detailPanel(label: string, description: string, details: string[]) {
  if (!details.length) return null;

  return (
    <div className="min-w-0 border border-omi-border-subtle bg-omi-surface px-3 py-2">
      <div className="text-xs font-semibold text-omi-text">{label}</div>
      <p className="mt-1 text-[11px] leading-5 text-omi-text-subtle">
        {description}
      </p>
      <div className="mt-2 flex min-w-0 flex-wrap gap-1.5 text-xs text-omi-text-muted">
        {details.map((detail) => (
          <span
            key={`${label}-${detail}`}
            className="inline-flex max-w-full items-start border border-omi-border-subtle bg-omi-surface-subtle px-1.5 py-0.5"
            title={detail}
          >
            <span className="min-w-0 break-words leading-5">{detail}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function detailCount(...detailGroups: string[][]) {
  return detailGroups.reduce((count, details) => count + details.length, 0);
}

function RadarLoadingRows() {
  return (
    <div className="omi-loading-surface divide-y divide-omi-border-subtle" aria-hidden="true">
      {Array.from({ length: 4 }).map((_, index) => (
        <div
          key={index}
          className="grid grid-cols-[42px_minmax(180px,1fr)_86px] items-center gap-3 px-4 py-3"
        >
          <span className="omi-skeleton h-3 w-7" />
          <span className="space-y-2">
            <span className="omi-skeleton block h-3 w-32" />
            <span className="omi-skeleton block h-2.5 w-64 max-w-full" />
          </span>
          <span className="omi-skeleton h-3 w-14" />
        </div>
      ))}
    </div>
  );
}

export default function WatchlistRadarPanel({
  radar,
  loadState,
  mode,
  selectedStockId,
  disabled = false,
  scopeLabel,
  notice,
  outcomeSummary,
  outcomeLoadState = "idle",
  outcomeHistory = [],
  outcomeHistoryOpen = false,
  outcomeHistoryLoadState = "idle",
  outcomeDetailLoadState = "idle",
  selectedOutcomeSnapshotId,
  getModeHref,
  onModeChange,
  onReload,
  onOpenOutcomeHistory,
  onCloseOutcomeHistory,
  onReloadOutcomeHistory,
  onSelectOutcomeSnapshot,
  onEvaluateOutcomeSnapshot,
  v2OutcomeHistory = [],
  v2OutcomeHistoryOpen = false,
  v2OutcomeHistoryLoadState = "idle",
  v2OutcomeDetailLoadState = "idle",
  selectedV2OutcomeSnapshotDate,
  onOpenV2OutcomeHistory,
  onCloseV2OutcomeHistory,
  onReloadV2OutcomeHistory,
  onSelectV2OutcomeSnapshot,
  onSelectStock,
}: WatchlistRadarPanelProps) {
  const t = useT();
  const isLoading = loadState === "loading" && radar === null;
  const hasResults = (radar?.results.length ?? 0) > 0;
  const activeBuckets = radar?.buckets.filter((bucket) => bucket.count > 0) ?? [];
  const activeBucketGroups = groupedRadarBuckets(activeBuckets);
  const radarV2IsActive =
    radar?.radar_engine?.mode === "active" &&
    radar.radar_engine.active_version === "radar_v2.0";
  const radarV2Readiness = radar?.radar_v2_summary?.readiness ?? null;
  const showOutcomeTools =
    !radarV2IsActive && Boolean(outcomeSummary || onOpenOutcomeHistory);
  const outcomeBusy = outcomeLoadState === "loading";
  const outcomeHistoryBusy = outcomeHistoryLoadState === "loading";
  const v2OutcomeHistoryBusy = v2OutcomeHistoryLoadState === "loading";
  const openActiveOutcomeHistory = radarV2IsActive
    ? onOpenV2OutcomeHistory
    : onOpenOutcomeHistory;
  const activeOutcomeHistoryBusy = radarV2IsActive
    ? v2OutcomeHistoryBusy
    : outcomeHistoryBusy;
  const outcomeDetailBusy = outcomeDetailLoadState === "loading";
  const outcomeBuckets = outcomeSummary?.bucket_summaries.slice(0, 4) ?? [];
  const selectedOutcomeSummary =
    outcomeHistory.find((summary) => summary.snapshot?.id === selectedOutcomeSnapshotId) ??
    outcomeHistory[0] ??
    outcomeSummary ??
    null;
  const selectedOutcomeSnapshotIdValue = selectedOutcomeSummary?.snapshot?.id ?? null;
  const selectedOutcomeBuckets = selectedOutcomeSummary?.bucket_summaries.slice(0, 8) ?? [];
  const radarDateLabel = radar?.trade_date
    ? t("radar.dateLabel", { date: formatRadarDate(radar.trade_date) })
    : t("radar.notLoaded");
  const radarSnapshotLabel =
    (radar?.cache_status === "snapshot" ||
      radar?.cache_status === "v2_snapshot") &&
    radar.snapshot_date
      ? t("radar.snapshotLabel", { date: formatRadarDate(radar.snapshot_date) })
      : null;

  return (
    <section className="border border-omi-border-subtle bg-omi-surface" data-testid="watchlist-radar-panel">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-omi-border-subtle px-5 py-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("radar.eyebrow")}
          </div>
          <h3 className="mt-1 text-lg font-bold text-omi-text-strong">{t("radar.title")}</h3>
          {scopeLabel ? (
            <p className="mt-1 text-xs font-medium text-omi-text-muted">
              {scopeLabel}
            </p>
          ) : null}
        </div>

        <div
          className="flex w-full min-w-0 flex-col items-start gap-2 md:w-auto md:items-end"
          data-testid="watchlist-radar-header-actions"
        >
          <div
            className="flex max-w-full flex-wrap items-center gap-2 md:justify-end"
            data-testid="watchlist-radar-controls"
          >
            <div className="mr-1 text-xs font-medium text-omi-text-muted">
              {radarDateLabel}
              {radarSnapshotLabel ? ` · ${radarSnapshotLabel}` : ""}
            </div>
            <div className="inline-flex border border-omi-border bg-omi-surface">
              {RADAR_MODE_OPTIONS.map((option) => (
                <a
                  key={option.value}
                  href={getModeHref?.(option.value) ?? "#"}
                  data-testid={`watchlist-radar-mode-${option.value}`}
                  title={t(option.titleKey)}
                  onClick={(event) => {
                    if (disabled || mode === option.value) {
                      event.preventDefault();
                      return;
                    }

                    event.preventDefault();
                    onModeChange(option.value);
                  }}
                  aria-disabled={disabled || mode === option.value}
                  className={[
                    "inline-flex h-8 items-center px-3 text-xs font-semibold",
                    mode === option.value
                      ? "bg-omi-control text-omi-text-inverse"
                      : "text-omi-text-muted hover:bg-omi-surface-subtle",
                  ].join(" ")}
                >
                  {t(option.labelKey)}
                </a>
              ))}
            </div>
            {openActiveOutcomeHistory ? (
              <button
                type="button"
                data-testid="watchlist-radar-history-open"
                onClick={openActiveOutcomeHistory}
                disabled={disabled || activeOutcomeHistoryBusy}
                className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:border-omi-border-subtle disabled:text-omi-text-subtle"
              >
                {t("radar.outcome.history")}
              </button>
            ) : null}
            <button
              type="button"
              data-testid="watchlist-radar-reload"
              onClick={onReload}
              disabled={disabled || loadState === "loading"}
              className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:border-omi-border-subtle disabled:text-omi-text-subtle"
            >
              {t("radar.reload")}
            </button>
          </div>
          {notice ? (
            <div
              className="inline-flex max-w-full items-center border border-omi-info-border bg-omi-info-soft px-2 py-1 text-xs leading-5 text-omi-info-strong"
              data-testid="watchlist-radar-notice"
            >
              <span className="min-w-0 break-words">{notice}</span>
            </div>
          ) : null}
        </div>
      </div>

      {radar?.radar_engine && radar.radar_v2_summary ? (
        <div
          className="border-b border-omi-border-subtle bg-omi-surface-subtle px-5 py-3"
          data-testid={
            radarV2IsActive
              ? "watchlist-radar-v2-active-summary"
              : "watchlist-radar-v2-shadow-summary"
          }
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-[0.14em] text-omi-text-muted">
                  {t("radar.v2.title")}
                </span>
                <span className="border border-omi-info-border bg-omi-info-soft px-2 py-0.5 text-xs font-semibold text-omi-info-strong">
                  {t(
                    radarV2IsActive
                      ? "radar.v2.activeBadge"
                      : "radar.v2.shadowBadge"
                  )}
                </span>
                <span className="text-xs text-omi-text-muted">
                  {radarV2IsActive
                    ? t("radar.v2.activeContract", {
                        active: radar.radar_engine.active_version,
                        rollback: radar.radar_engine.rollback_version,
                      })
                    : t("radar.v2.shadowContract", {
                        active: radar.radar_engine.active_version,
                        shadow: radar.radar_engine.shadow_version,
                      })}
                </span>
              </div>
              <p className="mt-1 text-xs text-omi-text-muted">
                {t(
                  radarV2IsActive
                    ? "radar.v2.activeNotice"
                    : "radar.v2.shadowNotice"
                )}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="border border-omi-border-subtle bg-omi-surface px-2 py-1 text-omi-text-muted">
                {t("radar.v2.summary.universeEvaluated", {
                  count: radar.radar_v2_summary.universe_evaluated_count,
                })}
              </span>
              <span className="border border-omi-warning-border bg-omi-warning-soft px-2 py-1 font-semibold text-omi-warning">
                {t("radar.v2.summary.conflict", {
                  count: radar.radar_v2_summary.conflict_count,
                })}
              </span>
              {radarV2IsActive && radarV2Readiness ? (
                <span
                  className={[
                    "border px-2 py-1 font-semibold",
                    radarV2Readiness.validation_status === "verified"
                      ? "border-omi-success-border bg-omi-success-soft text-omi-success"
                      : "border-omi-warning-border bg-omi-warning-soft text-omi-warning",
                  ].join(" ")}
                >
                  {t(
                    `radar.v2.validation.${radarV2Readiness.validation_status}`
                  )}
                </span>
              ) : (
                <span className="border border-omi-border-subtle bg-omi-surface px-2 py-1 text-omi-text-muted">
                  {t("radar.v2.summary.changed", {
                    count: radar.radar_v2_summary.direction_changed_count,
                  })}
                </span>
              )}
              <span className="border border-omi-border-subtle bg-omi-surface px-2 py-1 text-omi-text-muted">
                {t("radar.v2.summary.marketRegime", {
                  regime: radarV2Label(
                    t,
                    "regimes",
                    radar.radar_v2_summary.market_regime
                  ),
                })}
              </span>
            </div>
          </div>
        </div>
      ) : null}

      {radarV2IsActive ? (
        <WatchlistRadarV2OutcomePanel
          history={v2OutcomeHistory}
          historyOpen={v2OutcomeHistoryOpen}
          historyLoadState={v2OutcomeHistoryLoadState}
          detailLoadState={v2OutcomeDetailLoadState}
          selectedSnapshotDate={selectedV2OutcomeSnapshotDate}
          disabled={disabled}
          onCloseHistory={onCloseV2OutcomeHistory}
          onReloadHistory={onReloadV2OutcomeHistory}
          onSelectSnapshot={onSelectV2OutcomeSnapshot}
        />
      ) : null}

      {showOutcomeTools ? (
        <div className="border-b border-omi-border-subtle bg-omi-surface px-5 py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-[0.14em] text-omi-text-muted">
                  {t("radar.outcome.title")}
                </span>
                <span
                  className={[
                    "inline-flex max-w-full items-center border px-2 py-0.5 text-xs font-semibold",
                    outcomeStatusClass(outcomeSummary?.status),
                  ].join(" ")}
                >
                  {outcomeBusy
                    ? t("radar.outcome.loading")
                    : outcomeStatusText(t, outcomeSummary)}
                </span>
              </div>
              {outcomeSummary?.snapshot ? (
                <p className="mt-1 text-xs text-omi-text-muted">
                  {t("radar.outcome.snapshotMeta", {
                    date: formatRadarDate(outcomeSummary.snapshot.snapshot_date),
                    version: outcomeSummary.snapshot.radar_rule_version,
                  })}
                </p>
              ) : null}
            </div>
          </div>

          {outcomeSummary?.snapshot ? (
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1 text-omi-text-muted">
                {t("radar.outcome.stats.total", { count: outcomeSummary.total_count })}
              </span>
              <span className="border border-omi-success-border bg-omi-success-soft px-2 py-1 font-semibold text-omi-success">
                {t("radar.outcome.stats.hit", { count: outcomeSummary.hit_count })}
              </span>
              <span className="border border-omi-danger-border bg-omi-danger-soft px-2 py-1 font-semibold text-omi-danger">
                {t("radar.outcome.stats.miss", { count: outcomeSummary.miss_count })}
              </span>
              <span className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1 text-omi-text-muted">
                {t("radar.outcome.stats.neutral", { count: outcomeSummary.neutral_count })}
              </span>
              <span className="border border-omi-warning-border bg-omi-warning-soft px-2 py-1 font-semibold text-omi-warning">
                {t("radar.outcome.stats.pending", { count: outcomeSummary.pending_count })}
              </span>
              <span
                className={[
                  "border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1 font-semibold",
                  outcomeMetricClass(outcomeSummary.avg_close_return_pct),
                ].join(" ")}
              >
                {t("radar.outcome.stats.avgClose", {
                  value: formatRadarPct(outcomeSummary.avg_close_return_pct),
                })}
              </span>
            </div>
          ) : null}

          {outcomeBuckets.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-omi-text-muted">
              {outcomeBuckets.map((bucket) => (
                <span
                  key={bucket.bucket}
                  className="inline-flex items-center gap-1 border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1"
                >
                  <span className="font-semibold text-omi-text">
                    {radarBucketLabel(t, bucket.bucket, bucket.bucket_label)}
                  </span>
                  <span>{t("radar.outcome.bucketStat", {
                    hit: bucket.hit_count,
                    miss: bucket.miss_count,
                    pending: bucket.pending_count,
                  })}</span>
                </span>
              ))}
            </div>
          ) : null}

          {outcomeSummary?.data_limitations.length ? (
            <p className="mt-2 text-xs text-omi-text-muted">
              {outcomeSummary.data_limitations.join(" / ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {outcomeHistoryOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3"
          role="dialog"
          aria-modal="true"
          aria-label={t("radar.outcome.historyTitle")}
          data-testid="watchlist-radar-history-dialog"
        >
          <div className="flex max-h-[88vh] w-full max-w-6xl flex-col overflow-hidden border border-omi-border bg-omi-surface shadow-2xl">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-omi-border-subtle px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
                  {t("radar.outcome.title")}
                </div>
                <h3 className="mt-1 text-lg font-bold text-omi-text-strong">
                  {t("radar.outcome.historyTitle")}
                </h3>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {onReloadOutcomeHistory ? (
                  <button
                    type="button"
                    data-testid="watchlist-radar-history-reload"
                    onClick={onReloadOutcomeHistory}
                    disabled={disabled || outcomeHistoryBusy}
                    className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:border-omi-border-subtle disabled:text-omi-text-subtle"
                  >
                    {t("radar.outcome.reload")}
                  </button>
                ) : null}
                {onCloseOutcomeHistory ? (
                  <button
                    type="button"
                    onClick={onCloseOutcomeHistory}
                    className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent"
                  >
                    {t("radar.outcome.close")}
                  </button>
                ) : null}
              </div>
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[280px_minmax(0,1fr)]">
              <div className="min-h-0 overflow-y-auto border-b border-omi-border-subtle bg-omi-surface-subtle p-3 md:border-b-0 md:border-r">
                {outcomeHistoryBusy && outcomeHistory.length === 0 ? (
                  <div className="omi-loading-surface space-y-2">
                    {Array.from({ length: 4 }).map((_, index) => (
                      <div
                        key={index}
                        className="omi-skeleton h-16 border border-omi-border-subtle bg-omi-surface"
                      />
                    ))}
                  </div>
                ) : outcomeHistory.length > 0 ? (
                  <div className="space-y-2">
                    {outcomeHistory.map((summary) => {
                      const snapshotId = summary.snapshot?.id;
                      const selected = snapshotId === selectedOutcomeSnapshotIdValue;

                      return (
                        <button
                          key={snapshotId ?? summary.snapshot?.snapshot_date ?? "empty"}
                          type="button"
                          data-testid={
                            snapshotId
                              ? `watchlist-radar-history-snapshot-${snapshotId}`
                              : undefined
                          }
                          disabled={!snapshotId}
                          onClick={() => {
                            if (snapshotId) onSelectOutcomeSnapshot?.(snapshotId);
                          }}
                          className={[
                            "w-full border px-3 py-2 text-left transition",
                            selected
                              ? "border-omi-accent bg-omi-surface text-omi-text"
                              : "border-omi-border-subtle bg-omi-surface text-omi-text-muted hover:border-omi-accent",
                          ].join(" ")}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="font-semibold text-omi-text">
                              {formatRadarDate(summary.snapshot?.snapshot_date)}
                            </span>
                            <span
                              className={[
                                "border px-1.5 py-0.5 text-[11px] font-semibold",
                                outcomeStatusClass(summary.status),
                              ].join(" ")}
                            >
                              {outcomeStatusLabel(t, summary.status)}
                            </span>
                          </span>
                          <span className="mt-1 block text-xs">
                            {t("radar.outcome.savedSamples", {
                              count: outcomeSavedCount(summary),
                            })}
                            {" / "}
                            {t("radar.outcome.evaluatedSamples", {
                              count: summary.total_count,
                            })}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <StateSurface
                    title={t("radar.outcome.historyEmpty")}
                    tone="empty"
                    compact
                  />
                )}
              </div>

              <div className="min-h-0 overflow-y-auto p-5">
                {selectedOutcomeSummary?.snapshot ? (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-omi-text-muted">
                          {t("radar.outcome.snapshot")}
                        </div>
                        <h4 className="mt-1 text-xl font-bold text-omi-text-strong">
                          {formatRadarDate(selectedOutcomeSummary.snapshot.snapshot_date)}
                        </h4>
                        <p className="mt-1 text-xs text-omi-text-muted">
                          {t("radar.outcome.snapshotMeta", {
                            date: formatRadarDate(selectedOutcomeSummary.snapshot.snapshot_date),
                            version: selectedOutcomeSummary.snapshot.radar_rule_version,
                          })}
                        </p>
                      </div>
                      {selectedOutcomeSnapshotIdValue && onEvaluateOutcomeSnapshot ? (
                        <button
                          type="button"
                          data-testid="watchlist-radar-history-evaluate-selected"
                          onClick={() => onEvaluateOutcomeSnapshot(selectedOutcomeSnapshotIdValue)}
                          disabled={disabled || outcomeBusy}
                          className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:border-omi-border-subtle disabled:text-omi-text-subtle"
                        >
                          {t("radar.outcome.evaluateSelected")}
                        </button>
                      ) : null}
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                      <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
                        <div className="text-omi-text-muted">{t("radar.outcome.saved")}</div>
                        <div className="mt-1 text-lg font-bold text-omi-text">
                          {outcomeSavedCount(selectedOutcomeSummary)}
                        </div>
                      </div>
                      <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
                        <div className="text-omi-text-muted">{t("radar.outcome.evaluatedCount")}</div>
                        <div className="mt-1 text-lg font-bold text-omi-text">
                          {selectedOutcomeSummary.total_count}
                        </div>
                      </div>
                      <div className="border border-omi-success-border bg-omi-success-soft px-3 py-2">
                        <div className="text-omi-success">{t("radar.outcome.hit")}</div>
                        <div className="mt-1 text-lg font-bold text-omi-success">
                          {selectedOutcomeSummary.hit_count}
                        </div>
                      </div>
                      <div className="border border-omi-danger-border bg-omi-danger-soft px-3 py-2">
                        <div className="text-omi-danger">{t("radar.outcome.miss")}</div>
                        <div className="mt-1 text-lg font-bold text-omi-danger">
                          {selectedOutcomeSummary.miss_count}
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2 text-xs">
                      <span className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1 text-omi-text-muted">
                        {t("radar.outcome.stats.neutral", {
                          count: selectedOutcomeSummary.neutral_count,
                        })}
                      </span>
                      <span className="border border-omi-warning-border bg-omi-warning-soft px-2 py-1 font-semibold text-omi-warning">
                        {t("radar.outcome.stats.pending", {
                          count: selectedOutcomeSummary.pending_count,
                        })}
                      </span>
                      <span
                        className={[
                          "border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1 font-semibold",
                          outcomeMetricClass(selectedOutcomeSummary.avg_close_return_pct),
                        ].join(" ")}
                      >
                        {t("radar.outcome.stats.avgClose", {
                          value: formatRadarPct(selectedOutcomeSummary.avg_close_return_pct),
                        })}
                      </span>
                    </div>

                    <div>
                      <div className="mb-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
                        {t("radar.outcome.bucketSummary")}
                      </div>
                      {selectedOutcomeBuckets.length > 0 ? (
                        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                          {selectedOutcomeBuckets.map((bucket) => (
                            <div
                              key={bucket.bucket}
                              className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2 text-xs"
                            >
                              <div className="font-semibold text-omi-text">
                                {radarBucketLabel(t, bucket.bucket, bucket.bucket_label)}
                              </div>
                              <div className="mt-1 text-omi-text-muted">
                                {t("radar.outcome.bucketStat", {
                                  hit: bucket.hit_count,
                                  miss: bucket.miss_count,
                                  pending: bucket.pending_count,
                                })}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="flex flex-wrap gap-2 text-xs text-omi-text-muted">
                          {selectedOutcomeSummary.snapshot.buckets.map((bucket) => (
                            <span
                              key={bucket.key}
                              className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1"
                            >
                              {radarBucketLabel(t, bucket.key, bucket.label)} {bucket.count}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <div>
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                        <div className="font-bold uppercase tracking-wide text-omi-text-muted">
                          {t("radar.outcome.itemResults", {
                            count: outcomeSavedCount(selectedOutcomeSummary),
                          })}
                        </div>
                        <div className="text-omi-text-muted">
                          {t("radar.outcome.itemCoverage", {
                            shown: selectedOutcomeSummary.items.length,
                            total: outcomeSavedCount(selectedOutcomeSummary),
                          })}
                        </div>
                      </div>
                      {outcomeDetailBusy ? (
                        <StateSurface
                          title={t("radar.outcome.itemLoading")}
                          tone="loading"
                          busy
                          compact
                        />
                      ) : outcomeDetailLoadState === "error" ? (
                        <StateSurface
                          title={t("radar.outcome.loadError")}
                          tone="danger"
                          compact
                        />
                      ) : selectedOutcomeSummary.items.length > 0 ? (
                        <div
                          className="divide-y divide-omi-border-subtle border border-omi-border-subtle"
                          data-testid="watchlist-radar-history-items"
                        >
                          {selectedOutcomeSummary.items.map((item) => {
                            const radarItem = item.radar_item;
                            const signalDetails = radarItem
                              ? technicalSignalDetails(radarItem, t)
                              : [];
                            const scoreDetails = radarItem
                              ? factorScoreDetails(radarItem, t)
                              : [];
                            const levelDetails = radarItem
                              ? priceLevelDetails(radarItem, t)
                              : [];
                            const rawIndicatorDetails = radarItem
                              ? indicatorDetails(radarItem, t)
                              : [];
                            const indicatorDetailValues = rawIndicatorDetails.filter(
                              (detail) => !signalDetails.includes(detail)
                            );
                            const evaluationDetails = outcomeReviewDetails(item, t);
                            const collapsedDetailCount = detailCount(
                              evaluationDetails,
                              signalDetails,
                              scoreDetails,
                              levelDetails,
                              indicatorDetailValues
                            );

                            return (
                              <article
                                key={`${item.snapshot_item_id}-${item.stock_id}`}
                                className="bg-omi-surface text-xs"
                                data-testid={`watchlist-radar-history-item-${item.rank}-${item.stock_id}`}
                              >
                                <div className="grid grid-cols-[minmax(120px,1fr)_90px_90px] gap-3 px-3 py-2">
                                  <div className="min-w-0">
                                    <div className="truncate font-semibold text-omi-text">
                                      #{item.rank} {item.stock_id} {item.stock_name ?? ""}
                                    </div>
                                    <div className="mt-0.5 truncate text-omi-text-muted">
                                      {radarBucketLabel(t, item.bucket, item.bucket_label)}
                                    </div>
                                  </div>
                                  <div className="text-right">
                                    <div className="text-omi-text-muted">
                                      {t("radar.outcome.closeReturn")}
                                    </div>
                                    <div className={outcomeMetricClass(item.close_return_pct)}>
                                      {formatRadarPct(item.close_return_pct)}
                                    </div>
                                  </div>
                                  <div className="text-right">
                                    <div className="text-omi-text-muted">
                                      {t("radar.outcome.result")}
                                    </div>
                                    <span
                                      className={[
                                        "mt-0.5 inline-flex border px-1.5 py-0.5 font-semibold",
                                        outcomeStatusClass(item.status),
                                      ].join(" ")}
                                    >
                                      {outcomeStatusLabel(t, item.status)}
                                    </span>
                                  </div>
                                </div>
                                {collapsedDetailCount > 0 ? (
                                  <details
                                    className="group border-t border-omi-border-subtle px-3 pb-3 pt-2"
                                    data-testid={`watchlist-radar-history-item-details-${item.rank}-${item.stock_id}`}
                                  >
                                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-semibold text-omi-text-muted hover:text-omi-accent">
                                      <span className="min-w-0 truncate">
                                        {t("radar.outcome.itemDetailToggle", {
                                          count: collapsedDetailCount,
                                        })}
                                      </span>
                                      <span className="shrink-0 text-[11px] text-omi-text-subtle transition group-open:rotate-45">
                                        +
                                      </span>
                                    </summary>
                                    <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                                      {detailPanel(
                                        t("radar.outcome.detailSections.evaluation"),
                                        t("radar.outcome.detailDescriptions.evaluation"),
                                        evaluationDetails
                                      )}
                                      {detailPanel(
                                        t("radar.detailSections.signals"),
                                        t("radar.detailDescriptions.signals"),
                                        signalDetails
                                      )}
                                      {detailPanel(
                                        t("radar.detailSections.factors"),
                                        t("radar.detailDescriptions.factors"),
                                        scoreDetails
                                      )}
                                      {detailPanel(
                                        t("radar.detailSections.levels"),
                                        t("radar.detailDescriptions.levels"),
                                        levelDetails
                                      )}
                                      {detailPanel(
                                        t("radar.detailSections.indicators"),
                                        t("radar.detailDescriptions.indicators"),
                                        indicatorDetailValues
                                      )}
                                    </div>
                                  </details>
                                ) : null}
                              </article>
                            );
                          })}
                        </div>
                      ) : (
                        <StateSurface
                          title={t("radar.outcome.itemEmpty")}
                          tone="empty"
                          compact
                        />
                      )}
                    </div>
                  </div>
                ) : (
                  <StateSurface
                    title={t("radar.outcome.historyEmpty")}
                    tone="empty"
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {activeBuckets.length > 0 ? (
        <div className="flex flex-wrap items-stretch gap-y-2 border-b border-omi-border-subtle px-5 py-3">
          {activeBucketGroups.map((group, groupIndex) => (
            <div
              key={group.key}
              className={[
                "flex min-w-0 flex-wrap items-center gap-1.5 pr-3",
                groupIndex > 0 ? "border-l border-omi-border-subtle pl-3" : "",
              ].join(" ")}
            >
              <span className="text-[11px] font-bold text-omi-text-muted">
                {t(group.labelKey)}
              </span>
              {group.buckets.map((bucket) => (
                <span
                  key={bucket.key}
                  title={radarBucketDescription(t, bucket.key, bucket.description)}
                  className={[
                    "omi-signal-chip inline-flex items-center gap-1 border px-2 py-1 text-xs font-semibold",
                    bucketClass(bucket.key),
                  ].join(" ")}
                >
                  {radarBucketLabel(t, bucket.key, bucket.label)}
                  <span className="tabular-nums">{bucket.count}</span>
                </span>
              ))}
            </div>
          ))}
        </div>
      ) : null}

      {isLoading ? (
        <div>
          <div className="border-b border-omi-border-subtle p-3">
            <StateSurface
              eyebrow={t("radar.eyebrow")}
              title={t("common.loading")}
              tone="loading"
              busy
              compact
            />
          </div>
          <RadarLoadingRows />
        </div>
      ) : hasResults ? (
        <div
          className="max-h-[36rem] space-y-1 overflow-y-auto overscroll-contain bg-omi-surface-subtle p-2"
          tabIndex={0}
          aria-label={t("radar.resultsAria")}
        >
          {radar?.results.map((item) => {
            const selected = item.stock_id === selectedStockId;
            const visibleContextSignals = contextSignals(item);
            const bucketLabel = radarBucketLabel(t, item.bucket, item.bucket_label);
            const bucketDescription = radarBucketDescription(
              t,
              item.bucket,
              item.bucket_label
            );
            const technicalGradeLabel = radarTechnicalGradeLabel(
              t,
              item.technical_grade,
              item.technical_grade_label
            );
            const technicalGradeDescription = radarTechnicalGradeDescription(
              t,
              item.technical_grade,
              item.technical_grade_description
            );
            const radarScanLine = scanLine(item, t);
            const radarMeta = itemMeta(item, t);
            const signalDetails = technicalSignalDetails(item, t);
            const scoreDetails = factorScoreDetails(item, t);
            const v2Details = radarV2Details(item, t);
            const levelDetails = priceLevelDetails(item, t);
            const rawIndicatorDetails = indicatorDetails(item, t);
            const indicatorDetailValues = rawIndicatorDetails.filter(
              (detail) => !signalDetails.includes(detail)
            );
            const actionLabel =
              item.radar_v2?.rule_version === "radar_v2.0"
                ? item.action_label
                : radarActionLabel(
                    t,
                    item.bucket,
                    item.action_label,
                    item.stale
                  );
            const collapsedDetailCount = detailCount(
              signalDetails,
              scoreDetails,
              v2Details,
              levelDetails,
              indicatorDetailValues
            );

            return (
              <article
                key={`${item.rank}-${item.stock_id}-${item.bucket}`}
                data-testid={`watchlist-radar-result-${item.stock_id}`}
                className={[
                  "relative border text-sm transition",
                  selected
                    ? "omi-radar-row-selected z-10 text-omi-text"
                    : "border-transparent bg-omi-surface text-omi-text hover:border-omi-border-subtle hover:bg-omi-surface hover:shadow-sm",
                ].join(" ")}
              >
                <button
                  type="button"
                  onClick={() => onSelectStock(item.stock_id, item.stock_name)}
                  className="grid w-full grid-cols-[42px_minmax(180px,1fr)_86px] items-center gap-3 px-4 py-3 text-left"
                >
                  <span className={selected ? "font-semibold text-omi-accent" : "text-omi-text-muted"}>
                    #{item.rank}
                  </span>
                  <span className="min-w-0">
                    <span
                      className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-1"
                      aria-label={`${item.stock_id} radar signals`}
                    >
                      <span className="shrink-0 truncate font-semibold">
                        {item.stock_id} {item.stock_name ?? ""}
                      </span>
                      {signalBadge(
                        t("radar.badges.category"),
                        bucketLabel,
                        bucketClass(item.bucket),
                        bucketDescription
                      )}
                      {signalBadge(
                        t("radar.badges.urgency"),
                        urgencyLabel(t, item.urgency),
                        urgencyClass(item.urgency),
                        t("radar.badgeDescriptions.urgency")
                      )}
                      {signalBadge(
                        t("radar.badges.strength"),
                        technicalGradeLabel,
                        technicalGradeClass(item.technical_grade),
                        technicalGradeDescription
                      )}
                      {item.radar_v2
                        ? signalBadge(
                            t("radar.v2.badge"),
                            `${radarV2Label(
                              t,
                              "directions",
                              item.radar_v2.direction > 0
                                ? "bullish"
                                : item.radar_v2.direction < 0
                                  ? "bearish"
                                  : "neutral"
                            )} ${formatSignedRadarNumber(
                              item.radar_v2.direction_score,
                              0
                            ) ?? "0"} · ${radarV2Label(
                              t,
                              "grades",
                              item.radar_v2.evidence_grade
                            )}`,
                            radarV2DirectionClass(item.radar_v2.direction),
                            t("radar.v2.badgeDescription", {
                              confidence: item.radar_v2.confidence_score.toFixed(1),
                              conflict: item.radar_v2.conflict_score.toFixed(1),
                              risk: item.radar_v2.risk_score.toFixed(1),
                            })
                          )
                        : null}
                      {visibleContextSignals.map((signal) => {
                        const sourceLabel = radarContextSourceLabel(
                          t,
                          signal.key,
                          signal.source
                        );
                        const signalLabel = radarContextSignalLabel(t, signal.label);
                        const signalDescription = radarContextDescription(
                          t,
                          signal.key,
                          signal.description,
                          signal.value_label
                        );

                        return (
                          <span
                            key={`${signal.key}-${signal.label}`}
                            className={[
                              "omi-signal-chip inline-flex shrink-0 items-center gap-1 border px-1.5 py-0.5 text-[11px] font-semibold",
                              contextSignalClass(signal.tone, signal.stance),
                            ].join(" ")}
                            title={signalDescription}
                          >
                            <span className="text-[10px] opacity-75">{sourceLabel}：</span>
                            <span className="truncate">{signalLabel}</span>
                          </span>
                        );
                      })}
                    </span>
                    <span
                      className={selected ? "mt-1 block text-xs font-medium text-omi-text" : "mt-1 block text-xs font-medium text-omi-text-muted"}
                      title={radarScanLine}
                    >
                      {radarScanLine}
                    </span>
                    <span
                      className="mt-1 block text-xs text-omi-text-muted"
                      title={`${actionLabel} · ${radarMeta}`}
                    >
                      {actionLabel} · {radarMeta}
                    </span>
                  </span>
                  <span className="text-right">
                    <span className={`block font-semibold ${radarValueTone(item.change_pct)}`}>
                      {formatRadarPct(item.change_pct)}
                    </span>
                    <span className="block text-xs text-omi-text-muted">
                      {formatRadarPrice(item.close)}
                    </span>
                  </span>
                </button>
                {collapsedDetailCount > 0 ? (
                  <details className="group border-t border-omi-border-subtle px-4 pb-3 pt-2">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold text-omi-text-muted hover:text-omi-accent">
                      <span className="min-w-0 truncate">
                        {t("radar.detailToggle.label")}：{t("radar.detailToggle.summary", {
                          count: collapsedDetailCount,
                        })}
                      </span>
                      <span className="shrink-0 text-[11px] text-omi-text-subtle transition group-open:rotate-45">
                        +
                      </span>
                    </summary>
                    <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
                      {detailPanel(
                        t("radar.detailSections.signals"),
                        t("radar.detailDescriptions.signals"),
                        signalDetails
                      )}
                      {detailPanel(
                        t("radar.detailSections.factors"),
                        t("radar.detailDescriptions.factors"),
                        scoreDetails
                      )}
                      {detailPanel(
                        t("radar.v2.detailTitle"),
                        t("radar.v2.detailDescription"),
                        v2Details
                      )}
                      {detailPanel(
                        t("radar.detailSections.levels"),
                        t("radar.detailDescriptions.levels"),
                        levelDetails
                      )}
                      {detailPanel(
                        t("radar.detailSections.indicators"),
                        t("radar.detailDescriptions.indicators"),
                        indicatorDetailValues
                      )}
                    </div>
                  </details>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="p-3">
          <StateSurface
            eyebrow={t("radar.eyebrow")}
            title={
              loadState === "error"
                ? t("radar.loadError")
                : radar
                  ? t("radar.emptyWithRadar")
                  : t("radar.emptyNoGroup")
            }
            tone={loadState === "error" ? "danger" : "empty"}
            compact
          />
        </div>
      )}
    </section>
  );
}

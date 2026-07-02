"use client";

import type {
  WatchlistGroupRadarRead,
  WatchlistRadarItemRead,
  WatchlistRadarMode,
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
  errorMessage: string | null;
  mode: WatchlistRadarMode;
  selectedStockId: string | null;
  disabled?: boolean;
  scopeLabel?: string | null;
  notice?: string | null;
  getModeHref?: (mode: WatchlistRadarMode) => string;
  onModeChange: (mode: WatchlistRadarMode) => void;
  onReload: () => void;
  onSelectStock: (stockId: string, stockName: string | null) => void;
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

  return [
    levelDetail(t("radar.detailFields.support"), "support"),
    levelDetail(t("radar.detailFields.resistance"), "resistance"),
    levelDetail(t("radar.detailFields.ma20"), "ma20"),
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

  return [
    item.setup_label
      ? radarSetupLabel(t, item.bucket, item.setup_label)
      : bucketLabel,
    item.timing_label ? radarTimingLabel(t, item.bucket, item.timing_label) : null,
    item.risk_label ? radarRiskLabel(t, item.bucket, item.risk_label) : null,
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
    <div className="divide-y divide-omi-border-subtle">
      {Array.from({ length: 4 }).map((_, index) => (
        <div
          key={index}
          className="grid grid-cols-[42px_minmax(180px,1fr)_86px] items-center gap-3 px-4 py-3"
        >
          <span className="h-3 w-7 animate-pulse bg-omi-surface-strong" />
          <span className="space-y-2">
            <span className="block h-3 w-32 animate-pulse bg-omi-surface-strong" />
            <span className="block h-2.5 w-64 animate-pulse bg-omi-surface-muted" />
          </span>
          <span className="h-3 w-14 animate-pulse bg-omi-surface-muted" />
        </div>
      ))}
    </div>
  );
}

export default function WatchlistRadarPanel({
  radar,
  loadState,
  errorMessage,
  mode,
  selectedStockId,
  disabled = false,
  scopeLabel,
  notice,
  getModeHref,
  onModeChange,
  onReload,
  onSelectStock,
}: WatchlistRadarPanelProps) {
  const t = useT();
  const isLoading = loadState === "loading" && radar === null;
  const hasResults = (radar?.results.length ?? 0) > 0;
  const activeBuckets = radar?.buckets.filter((bucket) => bucket.count > 0) ?? [];
  const radarDateLabel = radar?.trade_date
    ? t("radar.dateLabel", { date: formatRadarDate(radar.trade_date) })
    : t("radar.notLoaded");

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

        <div className="flex flex-wrap items-center gap-2">
          <div className="mr-1 text-xs font-medium text-omi-text-muted">
            {radarDateLabel}
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
          <button
            type="button"
            onClick={onReload}
            disabled={disabled || loadState === "loading"}
            className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:border-omi-border-subtle disabled:text-omi-text-subtle"
          >
            {t("radar.reload")}
          </button>
        </div>
      </div>

      {errorMessage ? (
        <div className="border-b border-omi-warning-border bg-omi-warning-soft px-5 py-3 text-sm text-omi-warning">
          {errorMessage}
        </div>
      ) : null}

      {notice ? (
        <div className="border-b border-omi-info-border bg-omi-info-soft px-5 py-3 text-sm text-omi-info-strong">
          {notice}
        </div>
      ) : null}

      {activeBuckets.length > 0 ? (
        <div className="flex flex-wrap gap-2 border-b border-omi-border-subtle px-5 py-3">
          {activeBuckets.map((bucket) => (
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
      ) : null}

      {isLoading ? (
        <RadarLoadingRows />
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
            const levelDetails = priceLevelDetails(item, t);
            const rawIndicatorDetails = indicatorDetails(item, t);
            const indicatorDetailValues = rawIndicatorDetails.filter(
              (detail) => !signalDetails.includes(detail)
            );
            const actionLabel = radarActionLabel(
              t,
              item.bucket,
              item.action_label,
              item.stale
            );
            const collapsedDetailCount = detailCount(
              signalDetails,
              scoreDetails,
              levelDetails,
              indicatorDetailValues
            );

            return (
              <article
                key={`${item.rank}-${item.stock_id}-${item.bucket}`}
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
                    <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
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
        <div className="px-5 py-8 text-center text-sm text-omi-text-muted">
          {radar ? t("radar.emptyWithRadar") : t("radar.emptyNoGroup")}
        </div>
      )}
    </section>
  );
}

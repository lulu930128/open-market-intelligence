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
  getModeHref?: (mode: WatchlistRadarMode) => string;
  onModeChange: (mode: WatchlistRadarMode) => void;
  onReload: () => void;
  onSelectStock: (stockId: string, stockName: string | null) => void;
};

const RADAR_MODE_OPTIONS: Array<{ value: WatchlistRadarMode; labelKey: string }> = [
  { value: "action", labelKey: "radar.modes.action" },
  { value: "surge", labelKey: "radar.modes.surge" },
  { value: "breakout", labelKey: "radar.modes.breakout" },
  { value: "volume", labelKey: "radar.modes.volume" },
  { value: "overheat", labelKey: "radar.modes.overheat" },
  { value: "weakness", labelKey: "radar.modes.weakness" },
  { value: "risk", labelKey: "radar.modes.risk" },
  { value: "momentum", labelKey: "radar.modes.momentum" },
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
  if (bucket === "limit_up_lock" || bucket === "surge_up" || bucket === "limit_up_move") {
    return "omi-signal-chip-positive";
  }

  if (
    bucket === "limit_down_liquidity" ||
    bucket === "selloff_risk" ||
    bucket === "limit_down_move"
  ) {
    return "omi-signal-chip-negative";
  }

  if (
    bucket === "risk" ||
    bucket === "support_break" ||
    bucket === "volume_down" ||
    bucket === "bearish_momentum"
  ) {
    return "omi-signal-chip-danger";
  }

  if (bucket === "overheated") {
    return "omi-signal-chip-warning";
  }

  if (bucket === "volatility_risk") {
    return "omi-signal-chip-heat";
  }

  if (
    bucket === "breakout" ||
    bucket === "breakout_high" ||
    bucket === "trend_reclaim" ||
    bucket === "momentum"
  ) {
    return "omi-signal-chip-info";
  }

  if (
    bucket === "volume" ||
    bucket === "volume_up" ||
    bucket === "pullback" ||
    bucket === "compression_watch"
  ) {
    return "omi-signal-chip-warning";
  }

  return "omi-signal-chip-neutral";
}

function itemMeta(item: WatchlistRadarItemRead, t: TranslationFunction) {
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
  const uniqueTechnicalLabels = Array.from(new Set(technicalLabels)).slice(0, 3);

  return [
    bucketLabel,
    ...uniqueTechnicalLabels,
    item.stale ? t("radar.staleItem") : null,
  ]
    .filter(Boolean)
    .join(" · ");
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

      {radar?.is_current === false ? (
        <div className="border-b border-omi-warning-border bg-omi-warning-soft px-5 py-3 text-sm text-omi-warning">
          {t("radar.staleWarning", {
            count: radar.stale_stock_count,
            targetDate: formatRadarDate(radar.target_trade_date),
          })}
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
            const actionLabel = radarActionLabel(
              t,
              item.bucket,
              item.action_label,
              item.stale
            );

            return (
              <button
                key={`${item.rank}-${item.stock_id}-${item.bucket}`}
                type="button"
                onClick={() => onSelectStock(item.stock_id, item.stock_name)}
                className={[
                  "relative grid w-full grid-cols-[42px_minmax(180px,1fr)_86px] items-center gap-3 border px-4 py-3 text-left text-sm transition",
                  selected
                    ? "omi-radar-row-selected z-10 text-omi-text"
                    : "border-transparent bg-omi-surface text-omi-text hover:border-omi-border-subtle hover:bg-omi-surface hover:shadow-sm",
                ].join(" ")}
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
                      urgencyClass(item.urgency)
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
                    className={selected ? "mt-1 block truncate text-xs font-medium text-omi-text" : "mt-1 block truncate text-xs font-medium text-omi-text-muted"}
                    title={radarScanLine}
                  >
                    {radarScanLine}
                  </span>
                  <span
                    className="mt-1 block truncate text-xs text-omi-text-muted"
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

"use client";

import type {
  WatchlistGroupRadarRead,
  WatchlistRadarItemRead,
  WatchlistRadarMode,
} from "@/types/market";

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

const RADAR_MODE_OPTIONS: Array<{ value: WatchlistRadarMode; label: string }> = [
  { value: "action", label: "重點" },
  { value: "surge", label: "急漲" },
  { value: "breakout", label: "突破" },
  { value: "volume", label: "量能" },
  { value: "overheat", label: "過熱" },
  { value: "weakness", label: "弱勢" },
  { value: "risk", label: "風險" },
  { value: "momentum", label: "動能" },
];

const URGENCY_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

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
    return "text-slate-500";
  }

  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
}

function urgencyClass(value: string) {
  if (value === "high") return "border-red-200 bg-red-50 text-red-700";
  if (value === "medium") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function technicalGradeClass(value: string) {
  if (value === "strong") return "border-red-200 bg-red-50 text-red-700";
  if (value === "medium") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function contextSignalClass(tone: string, stance: string) {
  if (stance === "contradict" || tone === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  if (tone === "positive") return "border-red-200 bg-red-50 text-red-700";
  if (tone === "negative") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function bucketClass(bucket: string) {
  if (bucket === "limit_up_lock" || bucket === "surge_up" || bucket === "limit_up_move") {
    return "border-red-200 bg-red-50 text-red-700";
  }

  if (
    bucket === "limit_down_liquidity" ||
    bucket === "selloff_risk" ||
    bucket === "limit_down_move"
  ) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }

  if (
    bucket === "risk" ||
    bucket === "support_break" ||
    bucket === "volume_down" ||
    bucket === "bearish_momentum"
  ) {
    return "border-red-200 bg-red-50 text-red-700";
  }

  if (bucket === "overheated") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  if (bucket === "volatility_risk") {
    return "border-orange-200 bg-orange-50 text-orange-700";
  }

  if (
    bucket === "breakout" ||
    bucket === "breakout_high" ||
    bucket === "trend_reclaim" ||
    bucket === "momentum"
  ) {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }

  if (
    bucket === "volume" ||
    bucket === "volume_up" ||
    bucket === "pullback" ||
    bucket === "compression_watch"
  ) {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  return "border-slate-200 bg-slate-50 text-slate-600";
}

function itemMeta(item: WatchlistRadarItemRead) {
  const technicalLabels = [
    ...item.technical_notes,
    ...item.matched_signal_labels,
    item.primary_signal_label,
    ...item.signal_labels,
  ].filter(
    (label): label is string => Boolean(label) && label !== item.bucket_label
  );
  const uniqueTechnicalLabels = Array.from(new Set(technicalLabels)).slice(0, 3);

  return [
    item.bucket_label,
    ...uniqueTechnicalLabels,
    item.stale ? "資料待更新" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function keyLevelText(item: WatchlistRadarItemRead) {
  const label = item.price_levels.key_level_label;
  const value = item.price_levels.key_level;

  if (typeof label !== "string" || typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }

  return `${label} ${formatRadarPrice(value)}`;
}

function scanLine(item: WatchlistRadarItemRead) {
  return [
    item.setup_label || item.bucket_label,
    item.timing_label,
    item.risk_label,
    keyLevelText(item),
  ]
    .filter(Boolean)
    .join(" · ");
}

function contextSignals(item: WatchlistRadarItemRead) {
  return (item.context_signals ?? []).slice(0, 3);
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
        "inline-flex shrink-0 items-center gap-1 border px-1.5 py-0.5 text-[11px] font-semibold",
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
    <div className="divide-y divide-slate-100">
      {Array.from({ length: 4 }).map((_, index) => (
        <div
          key={index}
          className="grid grid-cols-[42px_minmax(180px,1fr)_86px] items-center gap-3 px-4 py-3"
        >
          <span className="h-3 w-7 animate-pulse bg-slate-200" />
          <span className="space-y-2">
            <span className="block h-3 w-32 animate-pulse bg-slate-200" />
            <span className="block h-2.5 w-64 animate-pulse bg-slate-100" />
          </span>
          <span className="h-3 w-14 animate-pulse bg-slate-100" />
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
  const isLoading = loadState === "loading" && radar === null;
  const hasResults = (radar?.results.length ?? 0) > 0;
  const activeBuckets = radar?.buckets.filter((bucket) => bucket.count > 0) ?? [];
  const radarDateLabel = radar?.trade_date
    ? `資料日 ${formatRadarDate(radar.trade_date)}`
    : "尚未載入";

  return (
    <section className="border border-slate-200 bg-white" data-testid="watchlist-radar-panel">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            Watchlist Radar
          </div>
          <h3 className="mt-1 text-lg font-bold text-slate-950">今日雷達</h3>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="mr-1 text-xs font-medium text-slate-500">
            {radarDateLabel}
          </div>
          <div className="inline-flex border border-slate-300 bg-white">
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
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-50",
                ].join(" ")}
              >
                {option.label}
              </a>
            ))}
          </div>
          <button
            type="button"
            onClick={onReload}
            disabled={disabled || loadState === "loading"}
            className="h-8 border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 hover:border-red-700 hover:text-red-700 disabled:border-slate-200 disabled:text-slate-400"
          >
            Reload
          </button>
        </div>
      </div>

      {errorMessage ? (
        <div className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-700">
          {errorMessage}
        </div>
      ) : null}

      {radar?.is_current === false ? (
        <div className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-700">
          自選股資料尚未完全同步，{radar.stale_stock_count} 檔落後目標日{" "}
          {formatRadarDate(radar.target_trade_date)}。
        </div>
      ) : null}

      {activeBuckets.length > 0 ? (
        <div className="flex flex-wrap gap-2 border-b border-slate-200 px-5 py-3">
          {activeBuckets.map((bucket) => (
            <span
              key={bucket.key}
              className={[
                "inline-flex items-center gap-1 border px-2 py-1 text-xs font-semibold",
                bucketClass(bucket.key),
              ].join(" ")}
            >
              {bucket.label}
              <span className="tabular-nums">{bucket.count}</span>
            </span>
          ))}
        </div>
      ) : null}

      {isLoading ? (
        <RadarLoadingRows />
      ) : hasResults ? (
        <div
          className="max-h-[36rem] space-y-1 overflow-y-auto overscroll-contain bg-slate-50/50 p-2"
          tabIndex={0}
          aria-label="Watchlist radar results"
        >
          {radar?.results.map((item) => {
            const selected = item.stock_id === selectedStockId;
            const visibleContextSignals = contextSignals(item);

            return (
              <button
                key={`${item.rank}-${item.stock_id}-${item.bucket}`}
                type="button"
                onClick={() => onSelectStock(item.stock_id, item.stock_name)}
                className={[
                  "relative grid w-full grid-cols-[42px_minmax(180px,1fr)_86px] items-center gap-3 border px-4 py-3 text-left text-sm transition",
                  selected
                    ? "z-10 -translate-y-px border-red-200 border-l-4 border-l-red-600 bg-white text-slate-900 shadow-[0_10px_24px_rgba(15,23,42,0.12)] ring-1 ring-red-100"
                    : "border-transparent bg-white text-slate-800 hover:border-slate-200 hover:bg-white hover:shadow-sm",
                ].join(" ")}
              >
                <span className={selected ? "font-semibold text-red-700" : "text-slate-500"}>
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
                      "分類",
                      item.bucket_label,
                      bucketClass(item.bucket)
                    )}
                    {signalBadge(
                      "急迫",
                      URGENCY_LABELS[item.urgency] ?? item.urgency,
                      urgencyClass(item.urgency)
                    )}
                    {signalBadge(
                      "強度",
                      item.technical_grade_label,
                      technicalGradeClass(item.technical_grade),
                      item.technical_grade_description
                    )}
                    {visibleContextSignals.map((signal) => (
                      <span
                        key={`${signal.key}-${signal.label}`}
                        className={[
                          "inline-flex shrink-0 items-center gap-1 border px-1.5 py-0.5 text-[11px] font-semibold",
                          contextSignalClass(signal.tone, signal.stance),
                        ].join(" ")}
                        title={signal.description}
                      >
                        <span className="text-[10px] opacity-75">{signal.source}：</span>
                        <span className="truncate">{signal.label}</span>
                      </span>
                    ))}
                  </span>
                  <span
                    className={selected ? "mt-1 block truncate text-xs font-medium text-slate-800" : "mt-1 block truncate text-xs font-medium text-slate-700"}
                    title={scanLine(item)}
                  >
                    {scanLine(item)}
                  </span>
                  <span
                    className="mt-1 block truncate text-xs text-slate-500"
                    title={item.reason}
                  >
                    {item.action_label} · {itemMeta(item)}
                  </span>
                </span>
                <span className="text-right">
                  <span className={`block font-semibold ${radarValueTone(item.change_pct)}`}>
                    {formatRadarPct(item.change_pct)}
                  </span>
                  <span className="block text-xs text-slate-500">
                    {formatRadarPrice(item.close)}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="px-5 py-8 text-center text-sm text-slate-500">
          {radar ? "目前沒有符合條件的雷達項目" : "選擇分組後顯示今日雷達"}
        </div>
      )}
    </section>
  );
}

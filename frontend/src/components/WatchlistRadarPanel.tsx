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
  { value: "risk", label: "風險" },
  { value: "momentum", label: "動能" },
  { value: "all", label: "全部" },
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

function bucketClass(bucket: string) {
  if (bucket === "risk" || bucket === "limit_move" || bucket === "limit_up_move") {
    return "border-red-200 bg-red-50 text-red-700";
  }

  if (bucket === "limit_down_move") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }

  if (bucket === "breakout" || bucket === "momentum") {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }

  if (bucket === "volume" || bucket === "pullback") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  return "border-slate-200 bg-slate-50 text-slate-600";
}

function itemMeta(item: WatchlistRadarItemRead) {
  return [
    item.bucket_label,
    item.primary_signal_label,
    item.stale ? "資料待更新" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function RadarLoadingRows() {
  return (
    <div className="divide-y divide-slate-100">
      {Array.from({ length: 4 }).map((_, index) => (
        <div
          key={index}
          className="grid grid-cols-[42px_minmax(180px,1fr)_92px_86px] items-center gap-3 px-4 py-3"
        >
          <span className="h-3 w-7 animate-pulse bg-slate-200" />
          <span className="space-y-2">
            <span className="block h-3 w-32 animate-pulse bg-slate-200" />
            <span className="block h-2.5 w-64 animate-pulse bg-slate-100" />
          </span>
          <span className="h-6 w-16 animate-pulse bg-slate-100" />
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
  const freshnessLabel =
    radar?.is_current === false
      ? `資料 ${radar.current_stock_count}/${radar.requested_stock_count} 檔已更新`
      : radar?.trade_date
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
          <div className="mt-1 text-xs text-slate-500">
            {radar ? `${radar.matched_count} 檔命中 · ${freshnessLabel}` : freshnessLabel}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
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
          {activeBuckets.slice(0, 6).map((bucket) => (
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
        <div className="divide-y divide-slate-100">
          {radar?.results.map((item) => {
            const selected = item.stock_id === selectedStockId;

            return (
              <button
                key={`${item.rank}-${item.stock_id}-${item.bucket}`}
                type="button"
                onClick={() => onSelectStock(item.stock_id, item.stock_name)}
                className={[
                  "grid w-full grid-cols-[42px_minmax(180px,1fr)_92px_86px] items-center gap-3 px-4 py-3 text-left text-sm",
                  selected ? "bg-slate-900 text-white" : "bg-white text-slate-800 hover:bg-slate-50",
                ].join(" ")}
              >
                <span className={selected ? "text-slate-300" : "text-slate-500"}>
                  #{item.rank}
                </span>
                <span className="min-w-0">
                  <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="truncate font-semibold">
                      {item.stock_id} {item.stock_name ?? ""}
                    </span>
                    <span
                      className={[
                        "border px-1.5 py-0.5 text-[11px] font-semibold",
                        selected ? "border-slate-500 bg-slate-800 text-slate-100" : urgencyClass(item.urgency),
                      ].join(" ")}
                    >
                      {URGENCY_LABELS[item.urgency] ?? item.urgency}
                    </span>
                  </span>
                  <span
                    className={selected ? "mt-1 block truncate text-xs text-slate-300" : "mt-1 block truncate text-xs text-slate-500"}
                    title={item.reason}
                  >
                    {item.action_label} · {itemMeta(item)}
                  </span>
                </span>
                <span className="text-right">
                  <span
                    className={[
                      "inline-flex border px-2 py-1 text-xs font-semibold",
                      selected ? "border-slate-500 bg-slate-800 text-slate-100" : bucketClass(item.bucket),
                    ].join(" ")}
                  >
                    {item.bucket_label}
                  </span>
                </span>
                <span className="text-right">
                  <span className={selected ? "block font-semibold" : `block font-semibold ${radarValueTone(item.change_pct)}`}>
                    {formatRadarPct(item.change_pct)}
                  </span>
                  <span className={selected ? "block text-xs text-slate-300" : "block text-xs text-slate-500"}>
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

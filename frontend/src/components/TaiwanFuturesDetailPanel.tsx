"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import { fetchJson } from "@/lib/api";
import type {
  ChartPoint,
  MarketIndexSummary,
  TaiwanFuturesDailyBar,
  TaiwanFuturesIntradayBar,
  TaiwanFuturesQuote,
} from "@/types/market";
import dynamic from "next/dynamic";
import { type ReactNode, useEffect, useMemo, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";

const LightweightKLineChart = dynamic(
  () => import("@/components/LightweightKLineChart"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[640px] items-center justify-center border-t border-slate-200 bg-white text-sm text-slate-500">
        K 線引擎載入中...
      </div>
    ),
  }
);

type Props = {
  marketIndexSummary?: MarketIndexSummary | null;
  symbol: string | null;
  onChartFocusModeChange?: (active: boolean) => void;
};

type FuturesTimeframe = "today" | "daily" | "weekly" | "monthly";

const FUTURES_ORDER = ["TXF", "MXF", "TMF"] as const;
const FUTURES_LABELS: Record<string, string> = {
  TXF: "大台",
  MXF: "小台",
  TMF: "微台",
};
const FUTURES_TIMEFRAMES: FuturesTimeframe[] = ["today", "daily", "weekly", "monthly"];
const FUTURES_TIMEFRAME_LABELS: Record<FuturesTimeframe, string> = {
  today: "今日",
  daily: "日K",
  weekly: "週K",
  monthly: "月K",
};

const numberFormatter = new Intl.NumberFormat("zh-TW", {
  maximumFractionDigits: 2,
});

const integerFormatter = new Intl.NumberFormat("zh-TW", {
  maximumFractionDigits: 0,
});

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return new Intl.NumberFormat("zh-TW", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits === 0 ? 0 : undefined,
  }).format(value);
}

function formatInteger(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return integerFormatter.format(value);
}

function formatSigned(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const prefix = value > 0 ? "+" : "";
  return `${prefix}${numberFormatter.format(value)}`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const prefix = value > 0 ? "+" : "";
  return `${prefix}${numberFormatter.format(value)}%`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("zh-TW", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function valueToneClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "text-slate-950";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";

  return "text-slate-950";
}

function valueToneBackground(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "bg-slate-100";
  if (value > 0) return "bg-red-50 text-red-700";
  if (value < 0) return "bg-emerald-50 text-emerald-700";

  return "bg-slate-100 text-slate-700";
}

function formatFuturesVolume(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return integerFormatter.format(value);
}

async function fetchLatestQuotes(symbols: readonly string[]) {
  const symbolParam = symbols.join(",");
  const rows = await fetchJson<TaiwanFuturesQuote[]>("/api/market/tw-futures/latest", {
    symbols: symbolParam,
    refresh: true,
    session: "auto",
  });

  if (rows.length > 0) return rows;

  return fetchJson<TaiwanFuturesQuote[]>("/api/market/tw-futures/latest", {
    symbols: symbolParam,
    refresh: true,
    session: "regular",
  });
}

function StatCell({
  label,
  note,
  toneValue,
  value,
}: {
  label: string;
  note?: string;
  toneValue?: number | null;
  value: ReactNode;
}) {
  return (
    <div className="border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div
        className={[
          "mt-1 text-base font-bold tabular-nums",
          toneValue === undefined ? "text-slate-950" : valueToneClass(toneValue),
        ].join(" ")}
      >
        {value}
      </div>
      {note ? <div className="mt-1 text-xs text-slate-500">{note}</div> : null}
    </div>
  );
}

function dailyBarToChartPoint(bar: TaiwanFuturesDailyBar): ChartPoint {
  return {
    time: bar.trade_date,
    open: bar.open_price,
    high: bar.high_price,
    low: bar.low_price,
    close: bar.close_price,
    volume: bar.total_volume,
    trade_value: null,
    transaction_count: null,
  };
}

function intradayBarToChartPoint(bar: TaiwanFuturesIntradayBar): ChartPoint {
  return {
    time: bar.bar_time,
    open: bar.open_price,
    high: bar.high_price,
    low: bar.low_price,
    close: bar.close_price,
    volume: bar.total_volume,
    trade_value: null,
    transaction_count: null,
  };
}

function isoDateKey(value: string) {
  return value.slice(0, 10);
}

function weekKey(value: string) {
  const date = new Date(`${isoDateKey(value)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return isoDateKey(value);

  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() - day + 1);
  return date.toISOString().slice(0, 10);
}

function aggregateChartPoints(points: ChartPoint[], mode: "weekly" | "monthly"): ChartPoint[] {
  const groups = new Map<string, ChartPoint[]>();

  points.forEach((point) => {
    if (point.close === null || point.close === undefined) return;

    const key = mode === "weekly" ? weekKey(point.time) : `${isoDateKey(point.time).slice(0, 7)}-01`;
    const rows = groups.get(key) ?? [];
    rows.push(point);
    groups.set(key, rows);
  });

  return Array.from(groups.entries()).map(([key, rows]) => {
    const first = rows[0];
    const last = rows[rows.length - 1];
    const highs = rows.map((row) => row.high).filter((value): value is number => value !== null);
    const lows = rows.map((row) => row.low).filter((value): value is number => value !== null);
    const volumes = rows.map((row) => row.volume).filter((value): value is number => value !== null);

    return {
      time: key,
      open: first?.open ?? null,
      high: highs.length > 0 ? Math.max(...highs) : null,
      low: lows.length > 0 ? Math.min(...lows) : null,
      close: last?.close ?? null,
      volume: volumes.length > 0 ? volumes.reduce((sum, value) => sum + value, 0) : null,
      trade_value: null,
      transaction_count: null,
    };
  });
}

function EmptyChartState({ loading, message }: { loading: boolean; message: string }) {
  return (
    <div className="flex min-h-[420px] items-center justify-center border border-slate-200 bg-white text-sm text-slate-500">
      {loading ? <LoadingDots label={message} /> : message}
    </div>
  );
}

function FuturesKLineVisual({
  chartData,
  expanded,
  indicators,
  loading,
  revealKey,
  timeframe,
}: {
  chartData: ChartPoint[];
  expanded: boolean;
  indicators: IndicatorSettings;
  loading: boolean;
  revealKey: string;
  timeframe: FuturesTimeframe;
}) {
  if (chartData.length < 1) {
    return (
      <EmptyChartState
        loading={loading}
        message={
          loading
            ? `${FUTURES_TIMEFRAME_LABELS[timeframe]}資料讀取中`
            : `${FUTURES_TIMEFRAME_LABELS[timeframe]}資料不足`
        }
      />
    );
  }

  if (expanded) {
    return (
      <LightweightKLineChart
        chartData={chartData}
        label={FUTURES_TIMEFRAME_LABELS[timeframe]}
        height={780}
        fillViewport
        timeMode={timeframe === "today" ? "intraday" : "date"}
        chartStyle="candlestick"
        showHeader={false}
        showMovingAverages={indicators.ma}
        indicators={indicators}
        indicatorParameters={defaultIndicatorParameters}
        volumePanelLabel={timeframe === "today" ? "累積量(口)" : "成交量(口)"}
        volumeValueKey="volume"
        drawingContext={{
          market: "TW_FUTURES",
          symbol: revealKey.split(":")[0] ?? null,
          timeframe,
        }}
      />
    );
  }

  return (
    <StockKLineChart
      chartData={chartData}
      label={FUTURES_TIMEFRAME_LABELS[timeframe]}
      indicators={indicators}
      indicatorParameters={defaultIndicatorParameters}
      revealKey={revealKey}
      volumePanelLabel={timeframe === "today" ? "累積量(口)" : "成交量(口)"}
      volumeTooltipLabel={timeframe === "today" ? "累積量(口)" : "成交量(口)"}
      volumeValueFormatter={formatFuturesVolume}
    />
  );
}

export default function TaiwanFuturesDetailPanel({
  marketIndexSummary = null,
  onChartFocusModeChange,
  symbol,
}: Props) {
  const [quotes, setQuotes] = useState<TaiwanFuturesQuote[]>([]);
  const [dailyBars, setDailyBars] = useState<TaiwanFuturesDailyBar[]>([]);
  const [bars, setBars] = useState<TaiwanFuturesIntradayBar[]>([]);
  const [quoteState, setQuoteState] = useState<LoadState>("idle");
  const [dailyState, setDailyState] = useState<LoadState>("idle");
  const [barsState, setBarsState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [chartTimeframe, setChartTimeframe] = useState<FuturesTimeframe>("daily");
  const [showChartIndicators, setShowChartIndicators] = useState(false);
  const [chartExpanded, setChartExpanded] = useState(false);

  useEffect(() => {
    onChartFocusModeChange?.(chartExpanded);
  }, [chartExpanded, onChartFocusModeChange]);

  useEffect(() => {
    return () => {
      onChartFocusModeChange?.(false);
    };
  }, [onChartFocusModeChange]);

  const normalizedSymbol = symbol?.trim().toUpperCase() || null;
  const quotesBySymbol = useMemo(() => {
    return new Map(quotes.map((quote) => [quote.symbol, quote]));
  }, [quotes]);
  const quote = normalizedSymbol ? quotesBySymbol.get(normalizedSymbol) ?? null : null;
  const displayProductName = normalizedSymbol
    ? `${normalizedSymbol} ${FUTURES_LABELS[normalizedSymbol] ?? quote?.product_name ?? "代表商品"}`
    : "TXF / MXF / TMF";

  useEffect(() => {
    if (!normalizedSymbol) {
      return;
    }

    const symbolKey = normalizedSymbol;
    let cancelled = false;

    async function loadQuotes() {
      setQuoteState("loading");
      setErrorMessage(null);

      try {
        const nextQuotes = await fetchLatestQuotes(FUTURES_ORDER);
        if (cancelled) return;

        setQuotes(nextQuotes);
        setQuoteState("success");
      } catch {
        if (cancelled) return;

        setQuoteState("error");
        setErrorMessage(null);
      }
    }

    async function loadBars() {
      setBarsState("loading");

      try {
        const nextBars = await fetchJson<TaiwanFuturesIntradayBar[]>(
          `/api/market/tw-futures/${encodeURIComponent(symbolKey)}/intraday`,
          { interval: "1m", limit: 180 }
        );
        if (cancelled) return;

        setBars(nextBars);
        setBarsState("success");
      } catch {
        if (cancelled) return;

        setBars([]);
        setBarsState("error");
      }
    }

    async function loadDailyBars() {
      setDailyState("loading");

      try {
        const cachedDailyBars = await fetchJson<TaiwanFuturesDailyBar[]>(
          `/api/market/tw-futures/${encodeURIComponent(symbolKey)}/daily`,
          { limit: 180, refresh: false, active_only: true }
        );
        if (cancelled) return;

        if (cachedDailyBars.length > 0) {
          setDailyBars(cachedDailyBars);
        }

        const refreshedDailyBars = await fetchJson<TaiwanFuturesDailyBar[]>(
          `/api/market/tw-futures/${encodeURIComponent(symbolKey)}/daily`,
          { limit: 180, refresh: true, lookback_days: 90, active_only: true }
        );
        if (cancelled) return;

        setDailyBars(refreshedDailyBars.length > 0 ? refreshedDailyBars : cachedDailyBars);
        setDailyState("success");
      } catch (error) {
        if (cancelled) return;

        try {
          const fallbackDailyBars = await fetchJson<TaiwanFuturesDailyBar[]>(
            `/api/market/tw-futures/${encodeURIComponent(symbolKey)}/daily`,
            { limit: 180, refresh: false, active_only: true }
          );
          if (cancelled) return;

          if (fallbackDailyBars.length > 0) {
            setDailyBars(fallbackDailyBars);
            setDailyState("success");
            return;
          }
        } catch {
          // Keep the primary fetch error below; the fallback only prevents clearing useful cache.
        }

        setDailyState("error");
        setErrorMessage(error instanceof Error ? error.message : "台指期日 K 回補失敗");
      }
    }

    void loadQuotes();
    void loadDailyBars();
    void loadBars();

    return () => {
      cancelled = true;
    };
  }, [normalizedSymbol]);

  const dailyChartData = useMemo(
    () => dailyBars.map(dailyBarToChartPoint).filter((point) => point.close !== null),
    [dailyBars]
  );
  const intradayChartData = useMemo(
    () => bars.map(intradayBarToChartPoint).filter((point) => point.close !== null),
    [bars]
  );
  const futuresChartData = useMemo(() => {
    if (chartTimeframe === "today") return intradayChartData;
    if (chartTimeframe === "weekly") return aggregateChartPoints(dailyChartData, "weekly");
    if (chartTimeframe === "monthly") return aggregateChartPoints(dailyChartData, "monthly");

    return dailyChartData;
  }, [chartTimeframe, dailyChartData, intradayChartData]);
  const futuresChartIndicators = useMemo<IndicatorSettings>(
    () => ({
      ...defaultIndicators,
      signals: false,
      ma: true,
      volume: true,
      rsi: showChartIndicators,
      macd: showChartIndicators,
      kd: showChartIndicators,
      atr: showChartIndicators,
      adx: showChartIndicators,
    }),
    [showChartIndicators]
  );
  const latestDailyBar = dailyBars[dailyBars.length - 1] ?? null;
  const latestIntradayBar = bars[bars.length - 1] ?? null;
  const latestPrice =
    quote?.last_price ?? latestDailyBar?.close_price ?? latestIntradayBar?.close_price ?? null;
  const displayChange = quote?.change ?? latestDailyBar?.change ?? null;
  const displayChangePct = quote?.change_pct ?? latestDailyBar?.change_pct ?? null;
  const quoteDirection = displayChange ?? displayChangePct;
  const recentBars = useMemo(() => bars.slice(-6).reverse(), [bars]);
  const chartLoading =
    chartTimeframe === "today" ? barsState === "loading" : dailyState === "loading";
  const taiexClose =
    marketIndexSummary?.indices.find((index) => index.index_id === "TAIEX")?.close ?? null;
  const basis =
    latestPrice !== null && latestPrice !== undefined && taiexClose !== null
      ? latestPrice - taiexClose
      : null;
  const renderTimeframeButtons = (mode: "normal" | "compact") => (
    <div
      className={[
        "flex border border-slate-200 bg-slate-50",
        mode === "compact" ? "p-0.5" : "p-1",
      ].join(" ")}
    >
      {FUTURES_TIMEFRAMES.map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => setChartTimeframe(item)}
          className={[
            mode === "compact"
              ? "h-7 px-2 text-xs font-semibold transition"
              : "h-8 min-w-12 px-3 text-sm font-semibold transition",
            chartTimeframe === item
              ? mode === "compact"
                ? "bg-slate-900 text-white"
                : "bg-red-700 text-white"
              : "text-slate-600 hover:bg-white hover:text-slate-950",
          ].join(" ")}
        >
          {FUTURES_TIMEFRAME_LABELS[item]}
        </button>
      ))}
    </div>
  );

  if (!normalizedSymbol) {
    return (
      <section className="border border-slate-200 bg-white px-5 py-10 text-center text-sm text-slate-500">
        請從左側選擇台指期商品
      </section>
    );
  }

  return (
    <section
      className={[
        "grid w-full grid-cols-1 items-start justify-start gap-4",
        chartExpanded ? "" : "xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className={["min-w-0 self-start", chartExpanded ? "space-y-0" : "space-y-4"].join(" ")}>
        {chartExpanded ? (
          <section className="border-x border-t border-slate-200 bg-white">
            <div className="border-b border-slate-200 px-4 py-2">
              <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  <div className="truncate text-lg font-bold text-slate-950">
                    台指期
                  </div>
                  <div
                    className={[
                      "flex items-baseline gap-2",
                      valueToneClass(quoteDirection),
                    ].join(" ")}
                  >
                    <PriceUpdatePulse
                      value={latestPrice}
                      direction={quoteDirection}
                      resetKey={`${normalizedSymbol}:focus:${chartTimeframe}`}
                      className="text-2xl font-bold leading-none tracking-normal tabular-nums"
                    >
                      {formatNumber(latestPrice)}
                    </PriceUpdatePulse>
                    <span className="text-sm font-semibold tabular-nums">
                      {formatSigned(displayChange)}
                    </span>
                    <span className="text-sm font-semibold tabular-nums">
                      ({formatPct(displayChangePct)})
                    </span>
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-end gap-1.5">
                  {renderTimeframeButtons("compact")}
                  <button
                    type="button"
                    onClick={() => setShowChartIndicators((value) => !value)}
                    className={[
                      "h-8 border px-3 text-xs font-semibold transition",
                      showChartIndicators
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-800 hover:border-slate-900 hover:text-slate-950",
                    ].join(" ")}
                  >
                    指標
                  </button>
                  <button
                    type="button"
                    onClick={() => setChartExpanded(false)}
                    className="h-8 border border-slate-900 bg-slate-900 px-3 text-xs font-semibold text-white hover:bg-slate-800"
                  >
                    總覽
                  </button>
                </div>
              </div>
            </div>
          </section>
        ) : (
          <section className="border border-slate-200 bg-white">
            <div className="grid gap-4 border-b border-slate-200 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_auto]">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                  FUTURES
                </div>
                <h2 className="mt-2 text-2xl font-black text-slate-950">台指期</h2>
                <div className="mt-2 text-sm text-slate-500">
                  TAIFEX · {displayProductName} ·{" "}
                  {quote?.session === "after_hours" ? "夜盤" : "日盤"} ·{" "}
                  {quote?.contract_month ?? latestDailyBar?.contract_month ?? "近月契約"}
                </div>
              </div>

              <div className="flex flex-wrap items-start justify-end gap-4 text-right">
                <div className="min-w-[180px]">
                  <PriceUpdatePulse
                    value={latestPrice}
                    direction={quoteDirection}
                    resetKey={normalizedSymbol}
                    className={[
                      "text-4xl font-black tabular-nums",
                      valueToneClass(quoteDirection),
                    ].join(" ")}
                  >
                    {quoteState === "loading" && latestPrice === null ? (
                      <LoadingDots label="台指期報價讀取中" />
                    ) : (
                      formatNumber(latestPrice)
                    )}
                  </PriceUpdatePulse>
                  <div
                    className={[
                      "mt-1 text-sm font-bold tabular-nums",
                      valueToneClass(quoteDirection),
                    ].join(" ")}
                  >
                    {formatSigned(displayChange)} / {formatPct(displayChangePct)}
                  </div>
                </div>

                <div className="flex flex-col items-end gap-2">
                  {renderTimeframeButtons("normal")}
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => setShowChartIndicators((value) => !value)}
                      className={[
                        "h-8 border px-3 text-sm font-semibold transition",
                        showChartIndicators
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-slate-900 bg-white text-slate-900 hover:border-red-700 hover:text-red-700",
                      ].join(" ")}
                    >
                      指標
                    </button>
                    <button
                      type="button"
                      onClick={() => setChartExpanded((value) => !value)}
                      className={[
                        "h-8 border px-3 text-sm font-semibold transition",
                        chartExpanded
                          ? "border-slate-900 bg-slate-900 text-white hover:bg-slate-800"
                          : "border-slate-300 bg-white text-slate-700 hover:border-slate-900 hover:text-slate-950",
                      ].join(" ")}
                    >
                      {chartExpanded ? "總覽" : "放大"}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid border-b border-slate-200 sm:grid-cols-2 xl:grid-cols-4">
              <div className="border-b border-r border-slate-200 px-5 py-4 xl:border-b-0">
                <div className="text-xs font-semibold text-slate-500">交易日</div>
                <div className="mt-1 font-black text-slate-950">
                  {formatDate(quote?.trade_date ?? latestDailyBar?.trade_date)}
                </div>
              </div>
              <div className="border-b border-r border-slate-200 px-5 py-4 xl:border-b-0">
                <div className="text-xs font-semibold text-slate-500">報價時間</div>
                <div className="mt-1 font-black text-slate-950">
                  {formatDateTime(quote?.quote_time ?? latestDailyBar?.fetched_at)}
                </div>
              </div>
              <div className="border-b border-r border-slate-200 px-5 py-4 sm:border-b-0">
                <div className="text-xs font-semibold text-slate-500">資料狀態</div>
                <div className="mt-1 font-black text-slate-950">
                  {quoteState === "loading" ? "更新中" : quote ? "已同步" : "尚無資料"}
                </div>
              </div>
              <div className="px-5 py-4">
                <div className="text-xs font-semibold text-slate-500">日 K 資料</div>
                <div className="mt-1 font-black text-slate-950">
                  {dailyState === "loading" ? "補資料中" : `${dailyBars.length} 根`}
                </div>
              </div>
            </div>

            {errorMessage ? (
              <div className="border-b border-red-100 bg-red-50 px-5 py-3 text-sm text-red-700">
                {errorMessage}
              </div>
            ) : null}
          </section>
        )}

      <div
        className={[
          "min-w-0",
          chartExpanded ? "border-x border-b border-slate-200 bg-white" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <FuturesKLineVisual
          chartData={futuresChartData}
          expanded={chartExpanded}
          indicators={futuresChartIndicators}
          loading={chartLoading}
          revealKey={`${normalizedSymbol}:${chartTimeframe}`}
          timeframe={chartTimeframe}
        />
      </div>

      {!chartExpanded ? (
        <section className="border border-slate-200 bg-white">
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
              SIGNAL
            </div>
            <h3 className="mt-1 text-lg font-black text-slate-950">期貨重點</h3>
          </div>
          <div className="grid gap-2 p-4 md:grid-cols-2 xl:grid-cols-3">
            <StatCell
              label="開盤"
              value={formatNumber(quote?.open_price ?? latestDailyBar?.open_price)}
            />
            <StatCell
              label="最高"
              value={formatNumber(quote?.high_price ?? latestDailyBar?.high_price)}
              toneValue={1}
            />
            <StatCell
              label="最低"
              value={formatNumber(quote?.low_price ?? latestDailyBar?.low_price)}
              toneValue={-1}
            />
            <StatCell
              label="參考 / 結算"
              value={formatNumber(quote?.reference_price ?? latestDailyBar?.settlement_price)}
            />
            <StatCell
              label="期現價差"
              note="TXF 對加權收盤"
              toneValue={basis}
              value={formatSigned(basis)}
            />
            <StatCell label="振幅" value={formatPct(quote?.amplitude_pct)} />
            <StatCell
              label="成交量"
              value={formatInteger(quote?.total_volume ?? latestDailyBar?.total_volume)}
            />
            <StatCell
              label="未平倉"
              value={formatInteger(quote?.open_interest ?? latestDailyBar?.open_interest)}
            />
            <StatCell
              label="買價 / 賣價"
              value={`${formatNumber(quote?.bid_price)} / ${formatNumber(quote?.ask_price)}`}
            />
          </div>
        </section>
      ) : null}
      </div>

      {!chartExpanded ? (
        <aside className="flex min-w-0 flex-col gap-4 self-start">
          <section className="border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                  CONTRACTS
                </div>
                <h3 className="mt-1 text-lg font-black text-slate-950">台指期商品比較</h3>
              </div>
              <div className="text-xs text-slate-500">TXF / MXF / TMF</div>
            </div>

            <div className="divide-y divide-slate-200">
              {FUTURES_ORDER.map((contractSymbol) => {
                const row = quotesBySymbol.get(contractSymbol) ?? null;

                return (
                  <div
                    key={contractSymbol}
                    className="bg-white p-5 text-slate-950"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                          {contractSymbol}
                        </div>
                        <div className="mt-1 text-xl font-black">
                          {FUTURES_LABELS[contractSymbol]}
                        </div>
                      </div>
                      <div
                        className={[
                          "px-2 py-1 text-xs font-bold",
                          valueToneBackground(row?.change_pct),
                        ].join(" ")}
                      >
                        {formatPct(row?.change_pct)}
                      </div>
                    </div>

                    <div
                      className={[
                        "mt-5 text-3xl font-black tabular-nums",
                        valueToneClass(row?.change),
                      ].join(" ")}
                    >
                      {formatNumber(row?.last_price)}
                    </div>
                    <div
                      className={[
                        "mt-1 text-sm font-bold tabular-nums",
                        valueToneClass(row?.change),
                      ].join(" ")}
                    >
                      {formatSigned(row?.change)}
                    </div>

                    <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <div className="text-slate-500">量</div>
                        <div className="font-bold tabular-nums">
                          {formatInteger(row?.total_volume)}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500">未平倉</div>
                        <div className="font-bold tabular-nums">
                          {formatInteger(row?.open_interest)}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500">最高</div>
                        <div className="font-bold tabular-nums">
                          {formatNumber(row?.high_price)}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500">最低</div>
                        <div className="font-bold tabular-nums">
                          {formatNumber(row?.low_price)}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                  DATA
                </div>
                <h3 className="mt-1 text-lg font-black text-slate-950">近期 1 分鐘資料</h3>
              </div>
              <div className="text-right text-xs text-slate-500">最近 6 根</div>
            </div>

            {recentBars.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500">
                    <tr>
                      <th className="px-5 py-2 text-left font-semibold">時間</th>
                      <th className="px-5 py-2 text-right font-semibold">開</th>
                      <th className="px-5 py-2 text-right font-semibold">高</th>
                      <th className="px-5 py-2 text-right font-semibold">低</th>
                      <th className="px-5 py-2 text-right font-semibold">收</th>
                      <th className="px-5 py-2 text-right font-semibold">累積量</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentBars.map((bar) => (
                      <tr key={bar.id} className="border-t border-slate-100">
                        <td className="px-5 py-2 text-slate-600">
                          {formatDateTime(bar.bar_time)}
                        </td>
                        <td className="px-5 py-2 text-right tabular-nums">
                          {formatNumber(bar.open_price)}
                        </td>
                        <td className="px-5 py-2 text-right tabular-nums text-red-600">
                          {formatNumber(bar.high_price)}
                        </td>
                        <td className="px-5 py-2 text-right tabular-nums text-emerald-600">
                          {formatNumber(bar.low_price)}
                        </td>
                        <td className="px-5 py-2 text-right font-bold tabular-nums">
                          {formatNumber(bar.close_price)}
                        </td>
                        <td className="px-5 py-2 text-right tabular-nums">
                          {formatInteger(bar.total_volume)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="px-5 py-10 text-center text-sm text-slate-500">
                {barsState === "loading" ? (
                  <LoadingDots label="1 分鐘資料讀取中" />
                ) : (
                  "尚無 1 分鐘資料，刷新報價後會逐步累積"
                )}
              </div>
            )}
          </section>
        </aside>
      ) : null}
    </section>
  );
}

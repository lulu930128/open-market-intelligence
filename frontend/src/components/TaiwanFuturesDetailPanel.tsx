"use client";

import { LoadingDots, StateSurface } from "@/components/LoadingPlaceholders";
import IntradayTrendChart, {
  defaultIntradayIndicators,
  type IntradayIndicatorSettings,
  type IntradaySessionConfig,
} from "@/components/IntradayTrendChart";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import ProfessionalChartPanel, {
  type ProfessionalChartStyle,
} from "@/components/ProfessionalChartPanel";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  indicatorCategoryDescription,
  indicatorCategoryLabel,
  indicatorOptionDescription,
  professionalIndicatorCategoryGroups,
  type IndicatorCategoryGroup,
  type IndicatorKey,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import type { ChartDrawing, ChartDrawingTool } from "@/components/LightweightKLineChart";
import {
  buildChartDrawingSnapshotPayload,
  chartDrawingApiPath,
  chartDrawingSnapshotsEqual,
  chartDrawingSyncDelayMs,
  createChartDrawingSnapshot,
  loadChartDrawings,
  normalizeChartDrawingSelection,
  normalizeStoredChartDrawings,
  saveChartDrawings,
  serializeChartDrawings,
  type ChartDrawingHistoryState,
  type ChartDrawingStorageState,
} from "@/components/professionalChartDrawing";
import { fetchJson, requestJson } from "@/lib/api";
import { emitDataStatusEvent, type DataStatusLevel } from "@/lib/dataStatusEvents";
import { getTaipeiMinutesOfDay } from "@/lib/taiwanMarketTime";
import { timeframeLabel, useT, type TranslationFunction } from "@/i18n";
import type {
  ChartDrawingSnapshotRead,
  ChartPoint,
  IntradayTrendPoint,
  MarketIndexSummary,
  TaiwanFuturesDailyBar,
  TaiwanFuturesDailyRefresh,
  TaiwanFuturesIntradayBar,
  TaiwanFuturesQuote,
} from "@/types/market";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";

type Props = {
  marketIndexSummary?: MarketIndexSummary | null;
  symbol: string | null;
  onChartFocusModeChange?: (active: boolean) => void;
};

type FuturesTimeframe = "today" | "daily" | "weekly" | "monthly";

const FUTURES_ORDER = ["TXF", "MXF", "TMF"] as const;
const FUTURES_TIMEFRAMES: FuturesTimeframe[] = ["today", "daily", "weekly", "monthly"];
const FUTURES_INTRADAY_REFRESH_MS = 30_000;
const FUTURES_REGULAR_SESSION_START_MINUTES = 8 * 60 + 45;
const FUTURES_REGULAR_SESSION_END_MINUTES = 13 * 60 + 45;
const FUTURES_AFTER_HOURS_SESSION_START_MINUTES = 15 * 60;
const FUTURES_AFTER_HOURS_SESSION_END_MINUTES = 24 * 60 + 5 * 60;

function clampRatio(value: number) {
  return Math.max(0, Math.min(1, value));
}

function getRegularSessionXRatio(value: string | Date) {
  const minutes = getTaipeiMinutesOfDay(value);
  if (minutes === null) return 0;

  return clampRatio(
    (minutes - FUTURES_REGULAR_SESSION_START_MINUTES) /
      (FUTURES_REGULAR_SESSION_END_MINUTES - FUTURES_REGULAR_SESSION_START_MINUTES)
  );
}

function getAfterHoursSessionMinutes(value: string | Date) {
  const minutes = getTaipeiMinutesOfDay(value);
  if (minutes === null) return null;

  return minutes <= 5 * 60 ? minutes + 24 * 60 : minutes;
}

function getAfterHoursSessionXRatio(value: string | Date) {
  const minutes = getAfterHoursSessionMinutes(value);
  if (minutes === null) return 0;

  return clampRatio(
    (minutes - FUTURES_AFTER_HOURS_SESSION_START_MINUTES) /
      (FUTURES_AFTER_HOURS_SESSION_END_MINUTES - FUTURES_AFTER_HOURS_SESSION_START_MINUTES)
  );
}

const futuresRegularIntradaySession: IntradaySessionConfig = {
  startMinutes: FUTURES_REGULAR_SESSION_START_MINUTES,
  endMinutes: FUTURES_REGULAR_SESSION_END_MINUTES,
  timeTicks: [
    { label: "08:45", minutes: 8 * 60 + 45 },
    { label: "09:45", minutes: 9 * 60 + 45 },
    { label: "10:45", minutes: 10 * 60 + 45 },
    { label: "11:45", minutes: 11 * 60 + 45 },
    { label: "12:45", minutes: 12 * 60 + 45 },
    { label: "13:45", minutes: 13 * 60 + 45 },
  ],
  getMinutesOfDay: getTaipeiMinutesOfDay,
  getXRatio: getRegularSessionXRatio,
  isRegularSessionPoint: (value) => {
    const minutes = getTaipeiMinutesOfDay(value);
    return (
      minutes !== null &&
      minutes >= FUTURES_REGULAR_SESSION_START_MINUTES &&
      minutes <= FUTURES_REGULAR_SESSION_END_MINUTES
    );
  },
  volumeFormatter: formatFuturesVolume,
};

const futuresAfterHoursIntradaySession: IntradaySessionConfig = {
  startMinutes: FUTURES_AFTER_HOURS_SESSION_START_MINUTES,
  endMinutes: FUTURES_AFTER_HOURS_SESSION_END_MINUTES,
  timeTicks: [
    { label: "15:00", minutes: 15 * 60 },
    { label: "17:00", minutes: 17 * 60 },
    { label: "19:00", minutes: 19 * 60 },
    { label: "21:00", minutes: 21 * 60 },
    { label: "23:00", minutes: 23 * 60 },
    { label: "01:00", minutes: 25 * 60 },
    { label: "03:00", minutes: 27 * 60 },
    { label: "05:00", minutes: 29 * 60 },
  ],
  getMinutesOfDay: getAfterHoursSessionMinutes,
  getXRatio: getAfterHoursSessionXRatio,
  isRegularSessionPoint: (value) => {
    const minutes = getAfterHoursSessionMinutes(value);
    return (
      minutes !== null &&
      minutes >= FUTURES_AFTER_HOURS_SESSION_START_MINUTES &&
      minutes <= FUTURES_AFTER_HOURS_SESSION_END_MINUTES
    );
  },
  volumeFormatter: formatFuturesVolume,
};

function chartDrawingStorageKey(symbol: string | null, timeframe: FuturesTimeframe) {
  return `omi:tw-futures:chart-drawings:v1:${symbol ?? "empty"}:${timeframe}`;
}

function chartDrawingTimeMode(timeframe: FuturesTimeframe) {
  return timeframe === "today" ? "intraday" : "date";
}

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
    second: "2-digit",
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

function futuresProductLabel(
  t: TranslationFunction,
  symbol: string | null | undefined,
  fallback?: string | null
) {
  if (!symbol) return fallback ?? "";

  const key = `futures.products.${symbol}`;
  const value = t(key);
  return value === key ? fallback ?? symbol : value;
}

function formatSessionLabel(t: TranslationFunction, value: string | null | undefined) {
  if (!value) return t("futures.sessions.unknown");
  if (value === "regular") return t("futures.sessions.regular");
  if (value === "after_hours") return t("futures.sessions.afterHours");
  return value;
}

function valueToneClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "text-omi-text-strong";
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";

  return "text-omi-text-strong";
}

function valueToneBackground(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "bg-omi-surface-muted";
  if (value > 0) return "bg-omi-danger-soft text-omi-danger";
  if (value < 0) return "bg-omi-success-soft text-omi-success";

  return "bg-omi-surface-muted text-omi-text";
}

function formatFuturesVolume(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return integerFormatter.format(value);
}

function quoteFreshnessToneClass(status: string | null | undefined) {
  if (status === "live") return "text-omi-success";
  if (status === "closed") return "text-omi-info";
  if (status === "cached" || status === "session_mismatch" || status === "stale") {
    return "text-omi-warning";
  }
  return "text-omi-text-strong";
}

function quoteFreshnessBannerClass(status: string | null | undefined) {
  if (status === "cached" || status === "session_mismatch" || status === "stale") {
    return "border-b border-omi-warning-border bg-omi-warning-soft px-5 py-3 text-sm text-omi-warning-strong";
  }
  return "border-b border-omi-border-subtle bg-omi-surface-subtle px-5 py-3 text-sm text-omi-text-muted";
}

function quoteFreshnessLabel(t: TranslationFunction, status: string | null | undefined) {
  if (status === "live") return t("futures.freshness.live");
  if (status === "closed") return t("futures.freshness.closed");
  if (status === "cached") return t("futures.freshness.cached");
  if (status === "session_mismatch") return t("futures.freshness.sessionMismatch");
  if (status === "stale") return t("futures.freshness.stale");
  return t("futures.freshness.none");
}

async function fetchLatestQuotes(symbols: readonly string[]) {
  const symbolParam = symbols.join(",");
  return fetchJson<TaiwanFuturesQuote[]>("/api/market/tw-futures/latest", {
    symbols: symbolParam,
    refresh: false,
    session: "auto",
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
    <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
      <div className="text-xs font-semibold text-omi-text-muted">{label}</div>
      <div
        className={[
          "mt-1 text-base font-bold tabular-nums",
          toneValue === undefined ? "text-omi-text-strong" : valueToneClass(toneValue),
        ].join(" ")}
      >
        {value}
      </div>
      {note ? <div className="mt-1 text-xs text-omi-text-muted">{note}</div> : null}
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
    <div className="flex min-h-[420px] items-center justify-center border border-omi-border-subtle bg-omi-surface p-4">
      <StateSurface
        title={message}
        tone={loading ? "loading" : "empty"}
        busy={loading}
        className="w-full max-w-xl"
      />
    </div>
  );
}

function FuturesProfessionalIndicatorMenu({
  groups = professionalIndicatorCategoryGroups,
  indicators,
  onToggleIndicator,
}: {
  groups?: IndicatorCategoryGroup[];
  indicators: IndicatorSettings;
  onToggleIndicator: (key: IndicatorKey) => void;
}) {
  const t = useT();

  return (
    <div className="absolute right-0 z-30 mt-2 max-h-[560px] w-[25rem] overflow-y-auto border border-omi-border-subtle bg-omi-surface p-3 text-left shadow-xl">
      <div className="mb-3 flex items-center justify-between border-b border-omi-border-subtle pb-2">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-muted">
            Indicators
          </div>
          <div className="mt-0.5 text-sm font-bold text-omi-text-strong">{t("chart.indicators")}</div>
        </div>
        <div className="text-[11px] font-semibold text-omi-text-subtle">{t("futures.productTitle")}</div>
      </div>

      <div className="space-y-3">
        {groups.map((group) => (
          <div key={group.key} className="border border-omi-border-subtle">
            <div className="border-b border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
              <div className="text-xs font-bold text-omi-text">
                {indicatorCategoryLabel(t, group)}
              </div>
              <div className="mt-0.5 text-[11px] text-omi-text-muted">
                {indicatorCategoryDescription(t, group)}
              </div>
            </div>
            <div className="grid grid-cols-1 gap-px bg-omi-surface-muted">
              {group.options.map((option) => {
                if (option.status !== "available") {
                  return (
                    <div
                      key={option.key}
                      className="flex items-start justify-between gap-2 bg-omi-surface px-3 py-2 text-xs text-omi-text-subtle"
                    >
                      <span>
                        <span className="block font-semibold">{option.label}</span>
                        <span className="block">{indicatorOptionDescription(t, option)}</span>
                      </span>
                      <span className="shrink-0 border border-omi-border-subtle px-1.5 py-0.5 text-[10px] font-bold">
                        {t("indicators.pending")}
                      </span>
                    </div>
                  );
                }

                return (
                  <label
                    key={option.key}
                    className="flex cursor-pointer items-start gap-2 bg-omi-surface px-3 py-2 text-xs hover:bg-omi-surface-subtle"
                  >
                    <input
                      type="checkbox"
                      checked={indicators[option.key]}
                      onChange={() => onToggleIndicator(option.key)}
                      className="mt-0.5"
                    />
                    <span>
                      <span className="block font-semibold text-omi-text">
                        {option.label}
                      </span>
                      <span className="block text-omi-text-muted">
                        {indicatorOptionDescription(t, option)}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FuturesKLineVisual({
  chartData,
  indicators,
  intradayIndicators,
  intradayPoints,
  intradayPreviousClose,
  intradaySession,
  intradayTotalVolume,
  intradayUpdatedAt,
  loading,
  revealKey,
  t,
  timeframe,
}: {
  chartData: ChartPoint[];
  indicators: IndicatorSettings;
  intradayIndicators: IntradayIndicatorSettings;
  intradayPoints: IntradayTrendPoint[];
  intradayPreviousClose: number | null;
  intradaySession: IntradaySessionConfig;
  intradayTotalVolume: number | null;
  intradayUpdatedAt: string | null;
  loading: boolean;
  revealKey: string;
  t: TranslationFunction;
  timeframe: FuturesTimeframe;
}) {
  const label = timeframeLabel(t, timeframe);

  if (timeframe === "today" && intradayPoints.length > 0) {
    return (
      <IntradayTrendChart
        points={intradayPoints}
        previousClose={intradayPreviousClose}
        label={label}
        source="TAIFEX MIS 1-minute chart"
        indicators={intradayIndicators}
        session={intradaySession}
        revealKey={revealKey}
        refreshIntervalMs={FUTURES_INTRADAY_REFRESH_MS}
        updatedAt={intradayUpdatedAt}
        priceLimitEnabled={false}
        totalVolume={intradayTotalVolume}
        volumeLabel={t("futures.volumeContracts")}
      />
    );
  }

  if (chartData.length < 1) {
    return (
      <EmptyChartState
        loading={loading}
        message={
          loading
            ? t("futures.loadingFrame", { label })
            : t("futures.insufficientFrame", { label })
        }
      />
    );
  }

  return (
    <StockKLineChart
      chartData={chartData}
      label={label}
      indicators={indicators}
      indicatorParameters={defaultIndicatorParameters}
      revealKey={revealKey}
      volumePanelLabel={t("futures.volumeContracts")}
      volumeTooltipLabel={t("futures.volumeContracts")}
      volumeValueFormatter={formatFuturesVolume}
    />
  );
}

export default function TaiwanFuturesDetailPanel({
  marketIndexSummary = null,
  onChartFocusModeChange,
  symbol,
}: Props) {
  const t = useT();
  const tRef = useRef(t);
  const [quotes, setQuotes] = useState<TaiwanFuturesQuote[]>([]);
  const [dailyBars, setDailyBars] = useState<TaiwanFuturesDailyBar[]>([]);
  const [bars, setBars] = useState<TaiwanFuturesIntradayBar[]>([]);
  const [quoteState, setQuoteState] = useState<LoadState>("idle");
  const [dailyState, setDailyState] = useState<LoadState>("idle");
  const [barsState, setBarsState] = useState<LoadState>("idle");
  const [chartTimeframe, setChartTimeframe] = useState<FuturesTimeframe>("daily");
  const [showChartIndicators, setShowChartIndicators] = useState(false);
  const [chartExpanded, setChartExpanded] = useState(false);
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [professionalChartStyle, setProfessionalChartStyle] =
    useState<ProfessionalChartStyle>("candlestick");
  const [professionalIndicators, setProfessionalIndicators] = useState<IndicatorSettings>(() => ({
    ...defaultIndicators,
    signals: false,
    ma: true,
    volume: true,
  }));
  const [chartDrawingTool, setChartDrawingTool] = useState<ChartDrawingTool>("cursor");
  const [selectedChartDrawingId, setSelectedChartDrawingId] = useState<string | null>(null);
  const [chartDrawingState, setChartDrawingState] = useState<ChartDrawingStorageState>({
    key: "",
    drawings: [],
  });
  const [chartDrawingHistoryState, setChartDrawingHistoryState] =
    useState<ChartDrawingHistoryState>({
      key: "",
      past: [],
      future: [],
    });
  const chartDrawingSyncTimerRef = useRef<number | null>(null);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    onChartFocusModeChange?.(chartExpanded);
  }, [chartExpanded, onChartFocusModeChange]);

  useEffect(() => {
    return () => {
      onChartFocusModeChange?.(false);
    };
  }, [onChartFocusModeChange]);

  const normalizedSymbol = useMemo(() => symbol?.trim().toUpperCase() || null, [symbol]);
  const quotesBySymbol = useMemo(() => {
    return new Map(quotes.map((quote) => [quote.symbol, quote]));
  }, [quotes]);
  const quote = normalizedSymbol ? quotesBySymbol.get(normalizedSymbol) ?? null : null;
  const displayProductName = normalizedSymbol
    ? `${normalizedSymbol} ${futuresProductLabel(
        t,
        normalizedSymbol,
        quote?.product_name ?? t("futures.products.representative")
      )}`
    : "TXF / MXF / TMF";
  const dataStatusContextKey = `tw:futures:${normalizedSymbol ?? "unknown"}`;
  const dataStatusContextLabel = normalizedSymbol
    ? `${normalizedSymbol} ${futuresProductLabel(
        t,
        normalizedSymbol,
        t("futures.products.representative")
      )}`
    : "TXF / MXF / TMF";
  const publishFuturesDataStatus = useCallback(
    ({
      level = "error",
      title,
      message,
      source = "台指期",
    }: {
      level?: DataStatusLevel;
      title: string;
      message: string;
      source?: string;
    }) => {
      if (!normalizedSymbol) return;

      emitDataStatusEvent({
        market: "tw",
        level,
        title,
        message,
        source,
        contextKey: dataStatusContextKey,
        contextLabel: dataStatusContextLabel,
        dedupeKey: `${dataStatusContextKey}:${source}:${title}:${level}`,
      });
    },
    [dataStatusContextKey, dataStatusContextLabel, normalizedSymbol]
  );
  const chartDrawingKey = chartDrawingStorageKey(normalizedSymbol, chartTimeframe);
  const storedChartDrawings = useMemo(
    () => loadChartDrawings(chartDrawingKey),
    [chartDrawingKey]
  );
  const chartDrawings =
    chartDrawingState.key === chartDrawingKey
      ? chartDrawingState.drawings
      : storedChartDrawings;
  const chartDrawingHistory =
    chartDrawingHistoryState.key === chartDrawingKey
      ? chartDrawingHistoryState
      : { key: chartDrawingKey, past: [], future: [] };
  const canUndoChartDrawing = chartDrawingHistory.past.length > 0;
  const canRedoChartDrawing = chartDrawingHistory.future.length > 0;
  const activeSelectedChartDrawingId = chartDrawings.some(
    (drawing) => drawing.id === selectedChartDrawingId
  )
    ? selectedChartDrawingId
    : null;

  useEffect(() => {
    if (!normalizedSymbol) {
      return;
    }

    const symbolKey = normalizedSymbol;
    let cancelled = false;

    async function loadQuotes(silent = false): Promise<TaiwanFuturesQuote[] | null> {
      if (!silent) {
        setQuoteState("loading");
      }

      try {
        const nextQuotes = await fetchLatestQuotes(FUTURES_ORDER);
        if (cancelled) return null;

        setQuotes(nextQuotes);
        setQuoteState("success");
        return nextQuotes;
      } catch (error) {
        if (cancelled) return null;

        setQuoteState("error");
        publishFuturesDataStatus({
          title: "台指期報價讀取失敗",
          message: error instanceof Error ? error.message : "台指期報價讀取失敗",
          source: "台指期報價",
        });
        return null;
      }
    }

    async function loadBars(silent = false, refresh = false) {
      if (!silent) {
        setBarsState("loading");
      }

      try {
        const intradayPath = `/api/market/tw-futures/${encodeURIComponent(symbolKey)}/intraday`;
        const nextBars = refresh
          ? await requestJson<TaiwanFuturesIntradayBar[]>(
              `${intradayPath}/refresh`,
              { method: "POST" },
              { interval: "1m", limit: 900, session: "auto" }
            )
          : await fetchJson<TaiwanFuturesIntradayBar[]>(intradayPath, {
              interval: "1m",
              limit: 900,
              refresh: false,
              session: "auto",
            });
        if (cancelled) return;

        setBars(nextBars);
        setBarsState("success");
      } catch (error) {
        if (cancelled) return;

        if (refresh) {
          try {
            const cachedBars = await fetchJson<TaiwanFuturesIntradayBar[]>(
              `/api/market/tw-futures/${encodeURIComponent(symbolKey)}/intraday`,
              { interval: "1m", limit: 900, refresh: false, session: "auto" }
            );
            if (cancelled) return;

            if (cachedBars.length > 0) {
              setBars(cachedBars);
              setBarsState("success");
              publishFuturesDataStatus({
                level: "warning",
                title: tRef.current("futures.errors.intradayRefreshFailed"),
                message: error instanceof Error ? error.message : String(error),
                source: "TAIFEX MIS 1-minute chart",
              });
              return;
            }
          } catch {
            // Continue with the primary refresh error when no usable cache exists.
          }
        }

        setBars([]);
        setBarsState("error");
        publishFuturesDataStatus({
          title: "台指期盤中資料讀取失敗",
          message: error instanceof Error ? error.message : "台指期盤中資料讀取失敗",
          source: "台指期盤中 K 線",
        });
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

        const refreshResult = await requestJson<TaiwanFuturesDailyRefresh>(
          `/api/market/tw-futures/${encodeURIComponent(symbolKey)}/daily/refresh`,
          { method: "POST" },
          { limit: 180, lookback_days: 90, active_only: true }
        );
        if (cancelled) return;

        if (refreshResult.warning) {
          publishFuturesDataStatus({
            title: "期貨日 K 更新範圍受限",
            message: refreshResult.warning,
            source: "TAIFEX 日成交行情",
            level: "warning",
          });
        }

        setDailyBars(refreshResult.rows.length > 0 ? refreshResult.rows : cachedDailyBars);
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
        const message =
          error instanceof Error
            ? error.message
            : tRef.current("futures.errors.dailyBackfillFailed");
        publishFuturesDataStatus({
          title: tRef.current("futures.errors.dailyBackfillFailed"),
          message,
          source: "台指期日 K",
        });
      }
    }

    async function loadInitialData() {
      const nextQuotes = await loadQuotes();
      if (cancelled) return;

      const selectedQuote = nextQuotes?.find((item) => item.symbol === symbolKey) ?? null;
      const shouldRefreshIntraday =
        selectedQuote?.freshness.market_status?.is_open ?? false;
      await loadBars(false, shouldRefreshIntraday);
    }

    void loadInitialData();
    void loadDailyBars();
    const liveRefreshTimer = window.setInterval(() => {
      void (async () => {
        const nextQuotes = await loadQuotes(true);
        if (cancelled) return;

        const selectedQuote = nextQuotes?.find((item) => item.symbol === symbolKey) ?? null;
        if (selectedQuote?.freshness.market_status?.is_open) {
          await loadBars(true, true);
        }
      })();
    }, FUTURES_INTRADAY_REFRESH_MS);

    return () => {
      cancelled = true;
      window.clearInterval(liveRefreshTimer);
    };
  }, [normalizedSymbol, publishFuturesDataStatus]);

  const dailyChartData = useMemo(
    () => dailyBars.map(dailyBarToChartPoint).filter((point) => point.close !== null),
    [dailyBars]
  );
  const intradayChartData = useMemo(
    () => bars.map(intradayBarToChartPoint).filter((point) => point.close !== null),
    [bars]
  );
  const futuresIntradayPoints = useMemo<IntradayTrendPoint[]>(
    () =>
      bars.flatMap((bar) =>
        bar.close_price === null
          ? []
          : [
              {
                time: bar.bar_time,
                session: bar.session,
                price: bar.close_price,
                volume: bar.total_volume,
                open: bar.open_price,
                high: bar.high_price,
                low: bar.low_price,
              },
            ]
      ),
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
  const futuresIntradayIndicators = useMemo<IntradayIndicatorSettings>(
    () => ({
      ...defaultIntradayIndicators,
      ema: showChartIndicators,
      rsi: showChartIndicators,
      macd: showChartIndicators,
    }),
    [showChartIndicators]
  );
  const latestDailyBar = dailyBars[dailyBars.length - 1] ?? null;
  const latestIntradayBar = bars[bars.length - 1] ?? null;
  const futuresIntradaySession =
    (quote?.session ?? latestIntradayBar?.session) === "after_hours"
      ? futuresAfterHoursIntradaySession
      : futuresRegularIntradaySession;
  const futuresIntradayPreviousClose =
    quote?.reference_price ?? latestDailyBar?.settlement_price ?? null;
  const latestPrice =
    quote?.last_price ?? latestDailyBar?.close_price ?? latestIntradayBar?.close_price ?? null;
  const displayChange = quote?.change ?? latestDailyBar?.change ?? null;
  const displayChangePct = quote?.change_pct ?? latestDailyBar?.change_pct ?? null;
  const quoteDirection = displayChange ?? displayChangePct;
  const quoteFreshness = quote?.freshness ?? null;
  const futuresMarketStatus = quoteFreshness?.market_status ?? null;
  const quoteFreshnessStatus =
    quoteState === "loading" ? "loading" : quoteFreshness?.status ?? null;
  const quoteFreshnessMessage =
    quoteState === "loading"
      ? t("futures.freshness.reloading")
      : quoteFreshness?.message ??
        (quote ? t("futures.freshness.pending") : t("futures.freshness.noQuote"));
  const quoteFreshnessTone =
    quoteState === "loading" ? "text-omi-info" : quoteFreshnessToneClass(quoteFreshnessStatus);
  const quoteFreshnessBanner =
    quoteFreshness && quoteFreshness.status !== "live" ? quoteFreshness : null;
  const displaySession = futuresMarketStatus?.is_open
    ? futuresMarketStatus.current_session
    : null;
  const displaySessionLabel = futuresMarketStatus
    ? futuresMarketStatus.is_open
      ? formatSessionLabel(t, displaySession)
      : t("futures.sessions.closed")
    : formatSessionLabel(t, quote?.session);
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
        "flex border border-omi-border-subtle bg-omi-surface-subtle",
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
                ? "bg-omi-control text-omi-text-inverse"
                : "bg-omi-accent text-omi-text-inverse"
              : "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong",
          ].join(" ")}
        >
          {timeframeLabel(t, item)}
        </button>
      ))}
    </div>
  );

  function toggleProfessionalIndicator(key: IndicatorKey) {
    setProfessionalIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  const professionalDrawingContext = useMemo(
    () => ({
      market: "TW_FUTURES",
      symbol: normalizedSymbol,
      timeframe: chartTimeframe,
    }),
    [chartTimeframe, normalizedSymbol]
  );

  const queueChartDrawingRemoteSave = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave: string | null
  ) => {
    if (typeof window === "undefined") return;
    if (!normalizedSymbol) return;

    const path = chartDrawingApiPath("TW_FUTURES", normalizedSymbol, chartTimeframe);
    const payload = buildChartDrawingSnapshotPayload({
      drawings: drawingsToSave,
      market: "TW_FUTURES",
      selectedDrawingId: selectedDrawingIdToSave,
      source: "frontend.tw_futures_professional_chart",
      stockName: displayProductName,
      symbol: normalizedSymbol,
      timeframe: chartTimeframe,
      timeMode: chartDrawingTimeMode(chartTimeframe),
    });

    if (chartDrawingSyncTimerRef.current) {
      window.clearTimeout(chartDrawingSyncTimerRef.current);
    }

    chartDrawingSyncTimerRef.current = window.setTimeout(() => {
      void requestJson<ChartDrawingSnapshotRead>(path, {
        method: "PUT",
        body: JSON.stringify(payload),
      }).catch(() => {
        // Best-effort server sync. Local chart drawings remain available via localStorage.
      });
    }, chartDrawingSyncDelayMs);
  }, [chartTimeframe, displayProductName, normalizedSymbol]);

  const storeChartDrawings = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave = activeSelectedChartDrawingId
  ) => {
    setChartDrawingState({
      key: chartDrawingKey,
      drawings: drawingsToSave,
    });
    saveChartDrawings(chartDrawingKey, drawingsToSave);
    queueChartDrawingRemoteSave(drawingsToSave, selectedDrawingIdToSave);
  }, [
    activeSelectedChartDrawingId,
    chartDrawingKey,
    queueChartDrawingRemoteSave,
  ]);

  useEffect(() => {
    return () => {
      if (chartDrawingSyncTimerRef.current && typeof window !== "undefined") {
        window.clearTimeout(chartDrawingSyncTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!chartExpanded || !normalizedSymbol) {
      return;
    }

    let cancelled = false;
    const remoteSymbol = normalizedSymbol;
    const localDrawings = loadChartDrawings(chartDrawingKey);
    const normalizedLocalSelection = normalizeChartDrawingSelection(
      localDrawings,
      activeSelectedChartDrawingId
    );

    if (localDrawings.length > 0) {
      queueChartDrawingRemoteSave(localDrawings, normalizedLocalSelection);
      return () => {
        cancelled = true;
      };
    }

    async function loadRemoteChartDrawings() {
      try {
        const snapshot = await fetchJson<ChartDrawingSnapshotRead>(
          chartDrawingApiPath("TW_FUTURES", remoteSymbol, chartTimeframe)
        );

        if (cancelled) return;

        const remoteDrawings = normalizeStoredChartDrawings(snapshot.drawings);
        if (remoteDrawings.length === 0) return;

        const remoteSelection = normalizeChartDrawingSelection(
          remoteDrawings,
          snapshot.selected_drawing_id
        );

        setChartDrawingState({
          key: chartDrawingKey,
          drawings: remoteDrawings,
        });
        saveChartDrawings(chartDrawingKey, remoteDrawings);
        setSelectedChartDrawingId(remoteSelection);
      } catch {
        // A missing remote snapshot simply means this chart has not been saved server-side yet.
      }
    }

    void loadRemoteChartDrawings();

    return () => {
      cancelled = true;
    };
  }, [
    activeSelectedChartDrawingId,
    chartDrawingKey,
    chartExpanded,
    chartTimeframe,
    normalizedSymbol,
    queueChartDrawingRemoteSave,
  ]);

  function updateChartDrawingState(
    nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
    nextSelectedDrawingId?: string | null,
    options: { recordHistory?: boolean } = {}
  ) {
    const nextDrawings =
      typeof nextValue === "function" ? nextValue(chartDrawings) : nextValue;
    const currentSnapshot = createChartDrawingSnapshot(
      chartDrawings,
      activeSelectedChartDrawingId
    );
    const nextSnapshot = createChartDrawingSnapshot(
      nextDrawings,
      nextSelectedDrawingId === undefined
        ? activeSelectedChartDrawingId
        : nextSelectedDrawingId
    );

    if (chartDrawingSnapshotsEqual(currentSnapshot, nextSnapshot)) {
      return;
    }

    if (
      serializeChartDrawings(currentSnapshot.drawings) ===
      serializeChartDrawings(nextSnapshot.drawings)
    ) {
      setSelectedChartDrawingId(nextSnapshot.selectedDrawingId);
      return;
    }

    if (options.recordHistory !== false) {
      const currentPast =
        chartDrawingHistoryState.key === chartDrawingKey ? chartDrawingHistoryState.past : [];

      setChartDrawingHistoryState({
        key: chartDrawingKey,
        past: [...currentPast, currentSnapshot].slice(-50),
        future: [],
      });
    }

    storeChartDrawings(nextSnapshot.drawings, nextSnapshot.selectedDrawingId);
    setSelectedChartDrawingId(nextSnapshot.selectedDrawingId);
  }

  function updateChartDrawings(
    nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
    options: { recordHistory?: boolean } = {}
  ) {
    updateChartDrawingState(nextValue, undefined, options);
  }

  const undoChartDrawing = useCallback(() => {
    if (!canUndoChartDrawing) return;

    const past = chartDrawingHistory.past;
    const previousSnapshot = past[past.length - 1];

    if (!previousSnapshot) return;

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: past.slice(0, -1),
      future: [
        createChartDrawingSnapshot(chartDrawings, activeSelectedChartDrawingId),
        ...chartDrawingHistory.future,
      ].slice(0, 50),
    });
    storeChartDrawings(previousSnapshot.drawings, previousSnapshot.selectedDrawingId);
    setSelectedChartDrawingId(previousSnapshot.selectedDrawingId);
  }, [
    activeSelectedChartDrawingId,
    canUndoChartDrawing,
    chartDrawingHistory.future,
    chartDrawingHistory.past,
    chartDrawingKey,
    chartDrawings,
    storeChartDrawings,
  ]);

  const redoChartDrawing = useCallback(() => {
    if (!canRedoChartDrawing) return;

    const nextDrawings = chartDrawingHistory.future[0];

    if (!nextDrawings) return;

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: [
        ...chartDrawingHistory.past,
        createChartDrawingSnapshot(chartDrawings, activeSelectedChartDrawingId),
      ].slice(-50),
      future: chartDrawingHistory.future.slice(1),
    });
    storeChartDrawings(nextDrawings.drawings, nextDrawings.selectedDrawingId);
    setSelectedChartDrawingId(nextDrawings.selectedDrawingId);
  }, [
    activeSelectedChartDrawingId,
    canRedoChartDrawing,
    chartDrawingHistory.future,
    chartDrawingHistory.past,
    chartDrawingKey,
    chartDrawings,
    storeChartDrawings,
  ]);

  function deleteSelectedChartDrawing() {
    if (!activeSelectedChartDrawingId) return;

    updateChartDrawings((current) =>
      current.filter((drawing) => drawing.id !== activeSelectedChartDrawingId)
    );
    setSelectedChartDrawingId(null);
  }

  function clearChartDrawings() {
    if (chartDrawings.length === 0) return;
    if (!window.confirm(t("futures.confirm.clearDrawings"))) return;

    updateChartDrawings([]);
    setSelectedChartDrawingId(null);
  }

  useEffect(() => {
    if (!chartExpanded) return;

    function handleChartDrawingHistoryKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();

      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;
      if (!event.ctrlKey && !event.metaKey) return;

      const key = event.key.toLowerCase();

      if (key === "z" && !event.shiftKey) {
        if (!canUndoChartDrawing) return;

        event.preventDefault();
        undoChartDrawing();
        return;
      }

      if (key === "y" || (key === "z" && event.shiftKey)) {
        if (!canRedoChartDrawing) return;

        event.preventDefault();
        redoChartDrawing();
      }
    }

    window.addEventListener("keydown", handleChartDrawingHistoryKeyDown);

    return () => window.removeEventListener("keydown", handleChartDrawingHistoryKeyDown);
  }, [
    canRedoChartDrawing,
    canUndoChartDrawing,
    chartExpanded,
    redoChartDrawing,
    undoChartDrawing,
  ]);

  if (!normalizedSymbol) {
    return (
      <section className="border border-omi-border-subtle bg-omi-surface px-5 py-10 text-center text-sm text-omi-text-muted">
        {t("futures.selectProduct")}
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
          <ProfessionalChartPanel
            title={`${normalizedSymbol} ${t("futures.productTitle")}`}
            priceSummary={
              <div
                className={["flex items-baseline gap-2", valueToneClass(quoteDirection)].join(" ")}
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
            }
            timeframeOptions={FUTURES_TIMEFRAMES.map((option) => ({
              key: option,
              label: timeframeLabel(t, option),
            }))}
            timeframe={chartTimeframe}
            onTimeframeChange={(nextTimeframe) => {
              setIndicatorMenuOpen(false);
              setChartTimeframe(nextTimeframe);
            }}
            chartStyle={professionalChartStyle}
            onChartStyleChange={setProfessionalChartStyle}
            indicatorMenuOpen={indicatorMenuOpen}
            onToggleIndicatorMenu={() => setIndicatorMenuOpen((value) => !value)}
            onCloseIndicatorMenu={() => setIndicatorMenuOpen(false)}
            indicatorMenu={
              <FuturesProfessionalIndicatorMenu
                indicators={professionalIndicators}
                onToggleIndicator={toggleProfessionalIndicator}
              />
            }
            onClose={() => {
              setIndicatorMenuOpen(false);
              setChartDrawingTool("cursor");
              setChartExpanded(false);
            }}
            chartReady={futuresChartData.length > 0}
            emptyState={
              <EmptyChartState
                loading={chartLoading}
                message={
                  chartLoading
                    ? t("futures.loadingFrame", {
                        label: timeframeLabel(t, chartTimeframe),
                      })
                    : t("futures.insufficientFrame", {
                        label: timeframeLabel(t, chartTimeframe),
                      })
                }
              />
            }
            chartData={futuresChartData}
            label={timeframeLabel(t, chartTimeframe)}
            timeMode={chartDrawingTimeMode(chartTimeframe)}
            showMovingAverages={professionalIndicators.ma}
            indicators={professionalIndicators}
            indicatorParameters={defaultIndicatorParameters}
            volumePanelLabel={t("futures.volumeContracts")}
            volumeValueKey="volume"
            drawingTool={chartDrawingTool}
            drawings={chartDrawings}
            selectedDrawingId={activeSelectedChartDrawingId}
            drawingContext={professionalDrawingContext}
            onDrawingToolChange={setChartDrawingTool}
            onDrawingsChange={updateChartDrawings}
            onDrawingStateChange={updateChartDrawingState}
            onSelectedDrawingChange={setSelectedChartDrawingId}
            canUndoDrawing={canUndoChartDrawing}
            canRedoDrawing={canRedoChartDrawing}
            onUndoDrawing={undoChartDrawing}
            onRedoDrawing={redoChartDrawing}
            onDeleteSelectedDrawing={deleteSelectedChartDrawing}
            onClearDrawings={clearChartDrawings}
            historyCounts={{
              past: chartDrawingHistory.past.length,
              future: chartDrawingHistory.future.length,
            }}
          />
        ) : (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <div className="grid gap-4 border-b border-omi-border-subtle px-5 py-5 lg:grid-cols-[minmax(0,1fr)_auto]">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em] text-omi-text-muted">
                  FUTURES
                </div>
                <h2 className="mt-2 text-2xl font-black text-omi-text-strong">{t("futures.productTitle")}</h2>
                <div className="mt-2 text-sm text-omi-text-muted">
                  TAIFEX · {displayProductName} ·{" "}
                  {displaySessionLabel} ·{" "}
                  {quote?.contract_month ?? latestDailyBar?.contract_month ?? t("futures.frontMonth")}
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
                      <LoadingDots label={t("futures.quoteLoading")} />
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
                          ? "border-omi-control bg-omi-control text-omi-text-inverse"
                          : "border-omi-control bg-omi-surface text-omi-text hover:border-omi-accent hover:text-omi-danger",
                      ].join(" ")}
                    >
                      {t("futures.indicators")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setChartExpanded((value) => !value)}
                      className={[
                        "h-8 border px-3 text-sm font-semibold transition",
                        chartExpanded
                          ? "border-omi-control bg-omi-control text-omi-text-inverse hover:bg-omi-control-muted"
                          : "border-omi-border bg-omi-surface text-omi-text hover:border-omi-control hover:text-omi-text-strong",
                      ].join(" ")}
                    >
                      {chartExpanded ? t("stockDetail.overview") : t("stockDetail.expand")}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid border-b border-omi-border-subtle sm:grid-cols-2 xl:grid-cols-4">
              <div className="border-b border-r border-omi-border-subtle px-5 py-4 xl:border-b-0">
                <div className="text-xs font-semibold text-omi-text-muted">{t("futures.tradeDate")}</div>
                <div className="mt-1 font-black text-omi-text-strong">
                  {formatDate(quote?.trade_date ?? latestDailyBar?.trade_date)}
                </div>
              </div>
              <div className="border-b border-r border-omi-border-subtle px-5 py-4 xl:border-b-0">
                <div className="text-xs font-semibold text-omi-text-muted">{t("futures.quoteTime")}</div>
                <div className="mt-1 font-black text-omi-text-strong">
                  {formatDateTime(quote?.quote_time ?? latestDailyBar?.fetched_at)}
                </div>
              </div>
              <div className="border-b border-r border-omi-border-subtle px-5 py-4 sm:border-b-0">
                <div className="text-xs font-semibold text-omi-text-muted">{t("futures.dataStatus")}</div>
                <div className={["mt-1 font-black", quoteFreshnessTone].join(" ")}>
                  {quoteState === "loading"
                    ? t("common.updating")
                    : quoteFreshnessLabel(t, quoteFreshnessStatus)}
                </div>
                <div className="mt-1 text-xs text-omi-text-muted">{quoteFreshnessMessage}</div>
                {futuresMarketStatus?.checked_at ? (
                  <div className="mt-1 text-xs text-omi-text-muted">
                    {t("futures.marketCheckedAt", {
                      time: formatDateTime(futuresMarketStatus.checked_at),
                    })}
                  </div>
                ) : null}
              </div>
              <div className="px-5 py-4">
                <div className="text-xs font-semibold text-omi-text-muted">{t("futures.dailyK")}</div>
                <div className="mt-1 font-black text-omi-text-strong">
                  {dailyState === "loading"
                    ? t("futures.backfilling")
                    : t("futures.bars", { count: dailyBars.length })}
                </div>
              </div>
            </div>

            {quoteFreshnessBanner ? (
              <div className={quoteFreshnessBannerClass(quoteFreshnessBanner.status)}>
                {quoteFreshnessBanner.message}
              </div>
            ) : null}
          </section>
        )}

      {!chartExpanded ? (
        <div className="min-w-0">
          <FuturesKLineVisual
            chartData={futuresChartData}
            indicators={futuresChartIndicators}
            intradayIndicators={futuresIntradayIndicators}
            intradayPoints={futuresIntradayPoints}
            intradayPreviousClose={futuresIntradayPreviousClose}
            intradaySession={futuresIntradaySession}
            intradayTotalVolume={quote?.total_volume ?? null}
            intradayUpdatedAt={latestIntradayBar?.updated_at ?? quote?.quote_time ?? null}
            loading={chartLoading}
            revealKey={`${normalizedSymbol}:${chartTimeframe}`}
            t={t}
            timeframe={chartTimeframe}
          />
        </div>
      ) : null}

      {!chartExpanded ? (
        <section className="border border-omi-border-subtle bg-omi-surface">
          <div className="border-b border-omi-border-subtle px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.22em] text-omi-text-muted">
              SIGNAL
            </div>
            <h3 className="mt-1 text-lg font-black text-omi-text-strong">{t("futures.signalTitle")}</h3>
          </div>
          <div className="grid gap-2 p-4 md:grid-cols-2 xl:grid-cols-3">
            <StatCell
              label={t("futures.open")}
              value={formatNumber(quote?.open_price ?? latestDailyBar?.open_price)}
            />
            <StatCell
              label={t("futures.high")}
              value={formatNumber(quote?.high_price ?? latestDailyBar?.high_price)}
              toneValue={1}
            />
            <StatCell
              label={t("futures.low")}
              value={formatNumber(quote?.low_price ?? latestDailyBar?.low_price)}
              toneValue={-1}
            />
            <StatCell
              label={t("futures.referenceSettlement")}
              value={formatNumber(quote?.reference_price ?? latestDailyBar?.settlement_price)}
            />
            <StatCell
              label={t("futures.basis")}
              note={t("futures.basisNote")}
              toneValue={basis}
              value={formatSigned(basis)}
            />
            <StatCell label={t("futures.amplitude")} value={formatPct(quote?.amplitude_pct)} />
            <StatCell
              label={t("dashboard.ranking.volume")}
              value={formatInteger(quote?.total_volume ?? latestDailyBar?.total_volume)}
            />
            <StatCell
              label={t("futures.openInterest")}
              value={formatInteger(quote?.open_interest ?? latestDailyBar?.open_interest)}
            />
            <StatCell
              label={t("futures.bidAsk")}
              value={`${formatNumber(quote?.bid_price)} / ${formatNumber(quote?.ask_price)}`}
            />
          </div>
        </section>
      ) : null}
      </div>

      {!chartExpanded ? (
        <aside className="flex min-w-0 flex-col gap-4 self-start">
          <section className="border border-omi-border-subtle bg-omi-surface">
            <div className="flex items-center justify-between border-b border-omi-border-subtle px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em] text-omi-text-muted">
                  CONTRACTS
                </div>
                <h3 className="mt-1 text-lg font-black text-omi-text-strong">{t("futures.contractsTitle")}</h3>
              </div>
              <div className="text-xs text-omi-text-muted">TXF / MXF / TMF</div>
            </div>

            <div className="divide-y divide-slate-200">
              {FUTURES_ORDER.map((contractSymbol) => {
                const row = quotesBySymbol.get(contractSymbol) ?? null;

                return (
                  <div
                    key={contractSymbol}
                    className="bg-omi-surface p-5 text-omi-text-strong"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                          {contractSymbol}
                        </div>
                        <div className="mt-1 text-xl font-black">
                          {futuresProductLabel(t, contractSymbol)}
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
                        <div className="text-omi-text-muted">{t("dashboard.ranking.volume")}</div>
                        <div className="font-bold tabular-nums">
                          {formatInteger(row?.total_volume)}
                        </div>
                      </div>
                      <div>
                        <div className="text-omi-text-muted">{t("futures.openInterest")}</div>
                        <div className="font-bold tabular-nums">
                          {formatInteger(row?.open_interest)}
                        </div>
                      </div>
                      <div>
                        <div className="text-omi-text-muted">{t("futures.high")}</div>
                        <div className="font-bold tabular-nums">
                          {formatNumber(row?.high_price)}
                        </div>
                      </div>
                      <div>
                        <div className="text-omi-text-muted">{t("futures.low")}</div>
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

          <section className="border border-omi-border-subtle bg-omi-surface">
            <div className="flex items-center justify-between border-b border-omi-border-subtle px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em] text-omi-text-muted">
                  DATA
                </div>
                <h3 className="mt-1 text-lg font-black text-omi-text-strong">{t("futures.recentMinuteTitle")}</h3>
              </div>
              <div className="text-right text-xs text-omi-text-muted">{t("futures.recentSixBars")}</div>
            </div>

            {recentBars.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-omi-surface-subtle text-xs text-omi-text-muted">
                    <tr>
                      <th className="px-5 py-2 text-left font-semibold">{t("futures.time")}</th>
                      <th className="px-5 py-2 text-right font-semibold">{t("futures.open")}</th>
                      <th className="px-5 py-2 text-right font-semibold">{t("futures.high")}</th>
                      <th className="px-5 py-2 text-right font-semibold">{t("futures.low")}</th>
                      <th className="px-5 py-2 text-right font-semibold">{t("futures.close")}</th>
                      <th className="px-5 py-2 text-right font-semibold">{t("futures.volumeContracts")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentBars.map((bar) => (
                      <tr key={bar.id} className="border-t border-omi-border-subtle">
                        <td className="px-5 py-2 text-omi-text-muted">
                          {formatDateTime(bar.bar_time)}
                        </td>
                        <td className="px-5 py-2 text-right tabular-nums">
                          {formatNumber(bar.open_price)}
                        </td>
                        <td className="px-5 py-2 text-right tabular-nums text-omi-market-up">
                          {formatNumber(bar.high_price)}
                        </td>
                        <td className="px-5 py-2 text-right tabular-nums text-omi-market-down">
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
              <div className="px-5 py-10 text-center text-sm text-omi-text-muted">
                {barsState === "loading" ? (
                  <LoadingDots label={t("futures.minuteLoading")} />
                ) : (
                  t("futures.noMinuteData")
                )}
              </div>
            )}
          </section>
        </aside>
      ) : null}
    </section>
  );
}

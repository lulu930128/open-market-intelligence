"use client";

import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import type { ChartDrawing, ChartDrawingTool } from "@/components/LightweightKLineChart";
import ProfessionalChartPanel, {
  type ProfessionalChartStyle,
} from "@/components/ProfessionalChartPanel";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  professionalIndicatorCategoryGroups,
  type IndicatorKey,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import {
  buildChartDrawingSnapshotPayload,
  chartDrawingApiPath,
  chartDrawingSnapshotsEqual,
  chartDrawingSyncDelayMs,
  createChartDrawingSnapshot,
  hasChartDrawingSnapshot,
  loadChartDrawings,
  normalizeChartDrawingSelection,
  normalizeStoredChartDrawings,
  saveChartDrawings,
  serializeChartDrawings,
  type ChartDrawingHistoryState,
  type ChartDrawingStorageState,
} from "@/components/professionalChartDrawing";
import TechnicalIndicatorMenu, {
  indicatorTemplates,
  type IndicatorTemplateKey,
} from "@/components/stock-detail/TechnicalIndicatorMenu";
import { useI18n, type TranslationFunction } from "@/i18n";
import { fetchJson, requestJson } from "@/lib/api";
import {
  clearDataStatusFocus,
  emitDataStatusEvent,
  setDataStatusFocus,
} from "@/lib/dataStatusEvents";
import {
  MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
  loadMarketDataSubscriptionSettings,
  marketDataSubscriptionItem,
  resourceSubscriptionAllowsAutoRefresh,
  resourceSubscriptionAllowsMissingDataRepair,
  resourceSubscriptionAllowsManualRefresh,
  resourceSelectedQuoteIntervalSeconds,
  resourceSubscriptionAllowsQuotePolling,
  type MarketDataSubscriptionItem,
  type MarketDataSubscriptionSettingsRead,
} from "@/lib/marketDataSubscriptions";
import type { ChartDrawingSnapshotRead, ChartPoint } from "@/types/market";
import {
  RESOURCE_OHLCV_INTERVALS,
  resourceInstrumentByKey,
  resourceSymbolFromKey,
  type ResourceCommodityInstrument,
  type ResourceInterval,
  type ResourceInstrumentRead,
  type ResourceOhlcvBar,
  type ResourceProviderContract,
  type ResourceQuoteSnapshot,
  type ResourceRefreshResult,
  type ResourceSourceHealth,
  type ResourceSourceHealthEntry,
} from "@/types/resourceMarket";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type ResourceOhlcvRefreshReason = "manual" | "auto_empty" | "auto_stale" | "on_select";
type ResourceDataView = "overview" | "move" | "compare" | "data" | "health";
type ResourceMetricCard = {
  key: string;
  label: string;
  value: string;
  detail?: string | null;
  valueClassName?: string;
};

type Props = {
  selectedInstrumentKey: string | null;
};

const DEFAULT_RESOURCE_INSTRUMENT_KEY = "commodity:metals:GC";
const DEFAULT_OVERVIEW_RESOURCE_INTERVALS: ResourceInterval[] = ["1m", "1d", "1w", "1M"];
const RESOURCE_CHART_LIMIT_BY_INTERVAL: Record<ResourceInterval, number> = {
  "1m": 4320,
  "5m": 1728,
  "15m": 2016,
  "30m": 2016,
  "1h": 2160,
  "1d": 2190,
  "1w": 1560,
  "1M": 720,
};
const RESOURCE_REFRESH_LIMIT_BY_INTERVAL: Record<ResourceInterval, number> = {
  "1m": 1440,
  "5m": 1728,
  "15m": 2016,
  "30m": 2016,
  "1h": 2160,
  "1d": 2190,
  "1w": 1560,
  "1M": 720,
};
const RESOURCE_REFRESH_TIMEOUT_MS = 45_000;
const RESOURCE_QUOTE_REFRESH_TIMEOUT_MS = 15_000;
const RESOURCE_AUTO_REFRESH_RETRY_BACKOFF_MS = 5 * 60 * 1000;
const RESOURCE_AUTO_REFRESH_ERROR_BACKOFF_MS = 10 * 60 * 1000;
const RESOURCE_AUTO_REFRESH_STALE_MS_BY_INTERVAL: Record<ResourceInterval, number> = {
  "1m": 2 * 60 * 1000,
  "5m": 5 * 60 * 1000,
  "15m": 15 * 60 * 1000,
  "30m": 30 * 60 * 1000,
  "1h": 60 * 60 * 1000,
  "1d": 6 * 60 * 60 * 1000,
  "1w": 24 * 60 * 60 * 1000,
  "1M": 7 * 24 * 60 * 60 * 1000,
};
const resourceChartIndicators: IndicatorSettings = {
  ...defaultIndicators,
  ma: true,
  volume: true,
  vwap: true,
  macd: false,
  rsi: false,
  signals: false,
};

function isResourceInterval(value: string): value is ResourceInterval {
  return RESOURCE_OHLCV_INTERVALS.includes(value as ResourceInterval);
}

function normalizeResourceIntervals(
  values: readonly string[] | null | undefined,
  fallback: readonly ResourceInterval[]
) {
  const intervals = (values ?? []).filter(isResourceInterval);
  return intervals.length ? intervals : [...fallback];
}

function contractChartProfileIntervals(
  contract: ResourceProviderContract | null,
  profile: "overview" | "professional",
  fallback: readonly ResourceInterval[]
) {
  return normalizeResourceIntervals(contract?.chart_profiles?.[profile]?.intervals, fallback);
}

function overviewIntervalLabel(interval: ResourceInterval, t: TranslationFunction) {
  if (interval === "1m") return t("crypto.summaryTimeframes.today");
  if (interval === "1d") return t("crypto.summaryTimeframes.daily");
  if (interval === "1w") return t("crypto.summaryTimeframes.weekly");
  if (interval === "1M") return t("crypto.summaryTimeframes.monthly");
  return t(`crypto.intervals.${interval}`);
}

function chartDrawingStorageKey(instrumentKey: string, interval: ResourceInterval) {
  return `omi:resource:chart-drawings:v1:${instrumentKey}:${interval}`;
}

function resourceDataStatusDedupeKey(symbol: string | null, interval: ResourceInterval) {
  return `resource:ohlcv:${symbol ?? "unknown"}:${interval}`;
}

function resourceDataStatusContextKey(symbol: string | null) {
  return `resource:${symbol ?? "unknown"}`;
}

function refreshIntervalsForMode(interval: ResourceInterval, professionalMode: boolean) {
  if (!professionalMode) {
    return interval;
  }
  if (interval === "1m") {
    return "1m,5m,15m";
  }
  return interval;
}

function refreshIntervalListForMode(
  interval: ResourceInterval,
  professionalMode: boolean
) {
  return refreshIntervalsForMode(interval, professionalMode).split(",") as ResourceInterval[];
}

function chartLimitForInterval(interval: ResourceInterval) {
  return RESOURCE_CHART_LIMIT_BY_INTERVAL[interval] ?? 500;
}

function refreshLimitForInterval(interval: ResourceInterval) {
  return RESOURCE_REFRESH_LIMIT_BY_INTERVAL[interval] ?? chartLimitForInterval(interval);
}

function refreshLimitForMode(interval: ResourceInterval, professionalMode: boolean) {
  return Math.max(
    ...refreshIntervalListForMode(interval, professionalMode).map(refreshLimitForInterval)
  );
}

function chartTimeMode(interval: ResourceInterval) {
  return ["1m", "5m", "15m", "30m", "1h"].includes(interval) ? "intraday" : "date";
}

function resourceRefreshReasonLabel(
  reason: ResourceOhlcvRefreshReason,
  t: TranslationFunction
) {
  if (reason === "auto_empty") return t("crypto.kline.refreshReasons.auto_empty");
  if (reason === "auto_stale") return t("crypto.kline.refreshReasons.auto_stale");
  if (reason === "on_select") return t("crypto.market.subscriptionModes.on_select");
  return t("crypto.kline.refreshReasons.manual");
}

function fallbackInstrumentToRead(
  instrument: ResourceCommodityInstrument | null
): ResourceInstrumentRead | null {
  if (!instrument) return null;

  return {
    key: instrument.key,
    root_folder: "commodity",
    group: instrument.group,
    asset_class: "commodity_futures",
    name: instrument.displayName,
    display_name: instrument.displayName,
    symbol: instrument.symbol,
    provider: "yahoo_chart",
    exchange: instrument.exchange,
    provider_symbol: instrument.providerSymbol,
    base_asset: instrument.symbol,
    quote_asset: instrument.quoteAsset,
    instrument_type: "futures",
    contract_type: "front_month",
    resources: ["quote", "ohlcv"],
    tradable: false,
    trade_candidate: false,
    provider_status: instrument.providerStatus,
    role: instrument.role,
  };
}

type LoadOutcome<T> =
  | { ok: true; label: string; value: T }
  | { ok: false; label: string; error: Error };

function normalizeLoadError(error: unknown) {
  return error instanceof Error ? error : new Error(String(error));
}

async function loadOutcome<T>(
  label: string,
  promise: Promise<T>
): Promise<LoadOutcome<T>> {
  try {
    return { ok: true, label, value: await promise };
  } catch (error) {
    return { ok: false, label, error: normalizeLoadError(error) };
  }
}

function loadFailureList(outcomes: readonly LoadOutcome<unknown>[]) {
  return outcomes.flatMap((outcome) =>
    outcome.ok ? [] : [{ label: outcome.label, error: outcome.error }]
  );
}

function loadFailureMessage(
  t: TranslationFunction,
  messageKey: string,
  failures: { label: string; error: Error }[]
) {
  const resources = failures
    .map((failure) => failure.label)
    .slice(0, 6)
    .join(", ");
  const detail = failures[0]?.error.message;
  const message = t(messageKey, { resources });
  return detail ? `${message}: ${detail}` : message;
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function formatSignedNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, digits)}`;
}

function formatPct(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("en-US", { maximumFractionDigits: digits })}%`;
}

function formatUnsignedPct(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toLocaleString("en-US", { maximumFractionDigits: digits })}%`;
}

function formatDateTimeShort(value: string | null | undefined, locale: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDurationSeconds(
  value: number | null | undefined,
  t: TranslationFunction
) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  if (value < 60) return t("crypto.resource.durationSeconds", { count: Math.max(0, Math.round(value)) });
  if (value < 60 * 60) return t("crypto.resource.durationMinutes", { count: Math.round(value / 60) });
  if (value < 24 * 60 * 60) {
    const hours = Math.floor(value / 3600);
    const minutes = Math.round((value % 3600) / 60);
    return minutes > 0
      ? t("crypto.resource.durationHoursMinutes", { hours, minutes })
      : t("crypto.resource.durationHours", { count: hours });
  }
  return t("crypto.resource.durationDays", { count: Math.round(value / (24 * 60 * 60)) });
}

function formatCompactText(value: string | null | undefined, maxLength = 160) {
  if (!value) return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}…` : normalized;
}

function formatVolume(value: number | null | undefined) {
  return formatNumber(value, 0);
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-omi-text-strong";
  }
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text-strong";
}

function subscriptionModeLabel(
  item: MarketDataSubscriptionItem | null,
  t: TranslationFunction
) {
  if (!item) return t("crypto.market.subscriptionModes.loading");
  if (item.mode === "always_on") return t("crypto.market.subscriptionModes.always_on");
  if (item.mode === "on_select") return t("crypto.market.subscriptionModes.on_select");
  if (item.mode === "manual") return t("crypto.market.subscriptionModes.manual");
  return t("crypto.market.subscriptionModes.disabled");
}

function statusClass(status: string | null | undefined) {
  if (status === "ok" || status === "live" || status === "success") {
    return "border-omi-success-border bg-omi-success-soft text-omi-success";
  }
  if (status === "error" || status === "failed") return "border-omi-danger/50 text-omi-danger";
  if (status === "disabled") return "border-omi-border text-omi-text-muted";
  return "border-omi-warning/40 text-omi-warning";
}

function providerStatusLabel(status: string | null | undefined, t: TranslationFunction) {
  if (!status || status === "provider_pending" || status === "pending") {
    return t("crypto.sidebar.providerPending");
  }
  if (status === "best_effort_delayed" || status === "best_effort") {
    return t("crypto.resource.providerBestEffortDelayed");
  }
  return status.replaceAll("_", " ");
}

function resourceHealthStatusLabel(status: string | null | undefined, t: TranslationFunction) {
  if (status === "delayed") return t("crypto.resource.healthDelayed");
  if (status === "stale") return t("crypto.market.status.stale");
  if (status === "empty") return t("crypto.resource.healthEmpty");
  if (status === "disabled") return t("crypto.market.status.disabled");
  if (status === "live" || status === "ok" || status === "success") {
    return t("crypto.market.status.ok");
  }
  if (status === "error" || status === "failed") return t("crypto.resource.healthError");
  return status?.replaceAll("_", " ") ?? "-";
}

function resourceSessionStatusLabel(status: string | null | undefined, t: TranslationFunction) {
  if (status === "open") return t("crypto.resource.sessionOpen");
  if (status === "closed") return t("crypto.resource.sessionClosed");
  if (status === "maintenance") return t("crypto.resource.sessionMaintenance");
  return t("crypto.resource.sessionUnknown");
}

function resourceHealthEntryHasIssue(entry: ResourceSourceHealthEntry) {
  return (
    !entry.ok ||
    (entry.recent_error_count ?? 0) > 0 ||
    entry.latest_event_status === "error" ||
    entry.latest_event_status === "failed"
  );
}

function resourceHealthEntryLabel(entry: ResourceSourceHealthEntry) {
  if (entry.resource === "ohlcv") return `${entry.target} K`;
  return entry.target;
}

function resourceHealthEntryDetail(
  entry: ResourceSourceHealthEntry,
  locale: string,
  t: TranslationFunction
) {
  const age = formatDurationSeconds(entry.age_seconds, t);
  const threshold = formatDurationSeconds(entry.stale_seconds, t);
  const freshness = age !== "-" && threshold !== "-"
    ? `${t("crypto.resource.sourceAge")} ${age} / ${t("crypto.resource.staleAfter")} ${threshold}`
    : formatDateTimeShort(entry.latest_fetched_at, locale);
  const freshnessDetail = freshness === "-" ? null : freshness;
  const eventDetail = entry.latest_event_message
    ? `${t("crypto.resource.lastEvent")} ${formatCompactText(entry.latest_event_message)}`
    : null;
  return eventDetail ?? freshnessDetail ?? entry.reason ?? "-";
}

function resourceLatestEventSummary(
  entry: ResourceSourceHealthEntry | null,
  locale: string,
  t: TranslationFunction
) {
  if (!entry?.latest_event_status) return "-";
  const status = resourceHealthStatusLabel(entry.latest_event_status, t);
  const eventTime = formatDateTimeShort(entry.latest_event_at, locale);
  return eventTime === "-" ? status : `${status} / ${eventTime}`;
}

function latestQuote(rows: readonly ResourceQuoteSnapshot[]) {
  return rows
    .slice()
    .sort((a, b) => Date.parse(b.fetched_at) - Date.parse(a.fetched_at))[0] ?? null;
}

function isoDateKey(value: string) {
  const datePart = value.slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(datePart)) return datePart;

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

function monthDateKey(value: string) {
  const dateKey = isoDateKey(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) return dateKey;
  return `${dateKey.slice(0, 7)}-01`;
}

function weekDateKey(value: string) {
  const dateKey = isoDateKey(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) return dateKey;

  const date = new Date(`${dateKey}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return dateKey;
  const daysFromMonday = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - daysFromMonday);
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

function resourceChartTimeKey(row: ResourceOhlcvBar, interval: ResourceInterval) {
  if (interval === "1M") return monthDateKey(row.bar_time);
  if (interval === "1w") return weekDateKey(row.bar_time);
  if (chartTimeMode(interval) === "date") return isoDateKey(row.bar_time);
  return row.bar_time;
}

function sortableTimeValue(value: string) {
  const timestamp = Date.parse(value.includes("T") ? value : `${value}T00:00:00Z`);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function resourceRowFreshness(row: ResourceOhlcvBar) {
  return sortableTimeValue(row.fetched_at) || sortableTimeValue(row.bar_time);
}

function resourceChartRefreshReason(
  chartRows: readonly ChartPoint[],
  healthEntry: ResourceSourceHealthEntry | null
): ResourceOhlcvRefreshReason | null {
  if (chartRows.length === 0) return "auto_empty";
  if (healthEntry?.status === "stale") return "auto_stale";
  return null;
}

function numericResultField(result: Record<string, unknown> | null | undefined, field: string) {
  const value = result?.[field];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function stringResultField(result: Record<string, unknown> | null | undefined, field: string) {
  const value = result?.[field];
  return typeof value === "string" ? value : "";
}

function resultForOhlcvInterval(
  result: ResourceRefreshResult,
  interval: ResourceInterval
): Record<string, unknown> | null {
  return (
    result.results?.find((item) => (
      item.resource === "ohlcv" &&
      item.interval === interval
    )) ?? null
  );
}

function barToChartPoint(row: ResourceOhlcvBar, time: string): ChartPoint {
  return {
    time,
    open: row.open_price,
    high: row.high_price,
    low: row.low_price,
    close: row.close_price,
    volume: row.volume,
    trade_value: null,
    transaction_count: null,
  };
}

function latestQuotesBySymbol(rows: readonly ResourceQuoteSnapshot[]) {
  const map = new Map<string, ResourceQuoteSnapshot>();
  rows.forEach((row) => {
    const existing = map.get(row.symbol);
    if (!existing || Date.parse(row.fetched_at) > Date.parse(existing.fetched_at)) {
      map.set(row.symbol, row);
    }
  });
  return map;
}

function dailyChartPointsFromBars(rows: readonly ResourceOhlcvBar[]) {
  const rowsByTime = new Map<string, ResourceOhlcvBar>();
  rows
    .filter((row) => row.interval === "1d" && row.close_price !== null)
    .forEach((row) => {
      const timeKey = isoDateKey(row.bar_time);
      const existing = rowsByTime.get(timeKey);
      if (!existing || resourceRowFreshness(row) >= resourceRowFreshness(existing)) {
        rowsByTime.set(timeKey, row);
      }
    });

  return Array.from(rowsByTime.entries())
    .sort(([leftTime], [rightTime]) => sortableTimeValue(leftTime) - sortableTimeValue(rightTime))
    .map(([time, row]) => barToChartPoint(row, time));
}

function pctChangeFromBase(current: number | null | undefined, base: number | null | undefined) {
  if (
    current === null ||
    current === undefined ||
    base === null ||
    base === undefined ||
    !Number.isFinite(current) ||
    !Number.isFinite(base) ||
    base === 0
  ) {
    return null;
  }
  return ((current - base) / base) * 100;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function pointBeforeOffset(points: readonly ChartPoint[], offset: number) {
  if (points.length <= offset) return null;
  return points[points.length - 1 - offset] ?? null;
}

function ytdBasePoint(points: readonly ChartPoint[]) {
  const latest = points[points.length - 1];
  if (!latest) return null;
  const latestYear = String(latest.time).slice(0, 4);
  return points.find((point) => String(point.time).slice(0, 4) === latestYear) ?? null;
}

function highLowStats(points: readonly ChartPoint[], lookback: number, current: number | null | undefined) {
  const rows = points.slice(-lookback);
  const highs = rows.map((row) => row.high).filter(isFiniteNumber);
  const lows = rows.map((row) => row.low).filter(isFiniteNumber);
  if (!rows.length || !highs.length || !lows.length) {
    return null;
  }
  const high = Math.max(...highs);
  const low = Math.min(...lows);
  const position = current !== null && current !== undefined && high > low
    ? ((current - low) / (high - low)) * 100
    : null;
  return { high, low, position };
}

function atrPct(points: readonly ChartPoint[], lookback = 14) {
  if (points.length < 2) return null;
  const rows = points.slice(-lookback);
  const ranges = rows.flatMap((row, index) => {
    const previous = points[points.length - rows.length + index - 1];
    const previousClose = previous?.close ?? row.close;
    if (!isFiniteNumber(row.high) || !isFiniteNumber(row.low) || !isFiniteNumber(previousClose)) {
      return [];
    }
    return Math.max(
      row.high - row.low,
      Math.abs(row.high - previousClose),
      Math.abs(row.low - previousClose)
    );
  });
  const latest = points[points.length - 1];
  if (!latest || !isFiniteNumber(latest.close) || latest.close === 0 || !ranges.length) return null;
  const atr = ranges.reduce((sum, value) => sum + value, 0) / ranges.length;
  return (atr / latest.close) * 100;
}

function quoteRatio(
  quoteBySymbol: Map<string, ResourceQuoteSnapshot>,
  numerator: string,
  denominator: string
) {
  const numeratorValue = quoteBySymbol.get(numerator)?.last_price;
  const denominatorValue = quoteBySymbol.get(denominator)?.last_price;
  if (
    numeratorValue === null ||
    numeratorValue === undefined ||
    denominatorValue === null ||
    denominatorValue === undefined ||
    !Number.isFinite(numeratorValue) ||
    !Number.isFinite(denominatorValue) ||
    denominatorValue === 0
  ) {
    return null;
  }
  return numeratorValue / denominatorValue;
}

export default function ResourceMarketPanel({ selectedInstrumentKey }: Props) {
  const { locale, t } = useI18n();
  const resolvedKey = selectedInstrumentKey ?? DEFAULT_RESOURCE_INSTRUMENT_KEY;
  const requestedSymbol = resourceSymbolFromKey(resolvedKey);
  const [interval, setInterval] = useState<ResourceInterval>("1m");
  const [professionalMode, setProfessionalMode] = useState(false);
  const [professionalChartStyle, setProfessionalChartStyle] =
    useState<ProfessionalChartStyle>("candlestick");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [contract, setContract] = useState<ResourceProviderContract | null>(null);
  const [instruments, setInstruments] = useState<ResourceInstrumentRead[]>([]);
  const [quotes, setQuotes] = useState<ResourceQuoteSnapshot[]>([]);
  const [allQuotes, setAllQuotes] = useState<ResourceQuoteSnapshot[]>([]);
  const [ohlcvBars, setOhlcvBars] = useState<ResourceOhlcvBar[]>([]);
  const [dailyBars, setDailyBars] = useState<ResourceOhlcvBar[]>([]);
  const [sourceHealth, setSourceHealth] = useState<ResourceSourceHealth | null>(null);
  const [subscriptionSettings, setSubscriptionSettings] =
    useState<MarketDataSubscriptionSettingsRead | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [activeDataView, setActiveDataView] = useState<ResourceDataView>("overview");
  const [chartIndicators, setChartIndicators] = useState<IndicatorSettings>(() => ({
    ...resourceChartIndicators,
  }));
  const [activeIndicatorTemplate, setActiveIndicatorTemplate] =
    useState<IndicatorTemplateKey | null>("basic");
  const [chartDrawingTool, setChartDrawingTool] = useState<ChartDrawingTool>("cursor");
  const [chartDrawingState, setChartDrawingState] = useState<ChartDrawingStorageState>({
    key: "",
    drawings: [],
  });
  const [selectedChartDrawingId, setSelectedChartDrawingId] = useState<string | null>(null);
  const [chartDrawingHistoryState, setChartDrawingHistoryState] =
    useState<ChartDrawingHistoryState>({
      key: "",
      past: [],
      future: [],
    });
  const chartDrawingSyncTimerRef = useRef<number | null>(null);
  const chartDrawingLocalRevisionRef = useRef(0);
  const dataRequestIdRef = useRef(0);
  const autoRefreshKeyRef = useRef<string | null>(null);
  const chartAutoRefreshAttemptsRef = useRef<Record<string, number>>({});
  const chartAutoRefreshInFlightRef = useRef<string | null>(null);
  const quotePollingRef = useRef(false);

  const fallbackInstrument = resourceInstrumentByKey(resolvedKey);
  const selectedInstrument = useMemo(() => {
    return (
      instruments.find((instrument) => instrument.key === resolvedKey) ??
      instruments.find((instrument) => instrument.symbol === requestedSymbol) ??
      fallbackInstrumentToRead(fallbackInstrument)
    );
  }, [fallbackInstrument, instruments, requestedSymbol, resolvedKey]);
  const selectedProvider = selectedInstrument?.provider ?? null;
  const supportedResourceIntervals = useMemo(() => {
    return normalizeResourceIntervals(
      selectedProvider ? contract?.ohlcv_intervals?.[selectedProvider] : null,
      RESOURCE_OHLCV_INTERVALS
    );
  }, [contract?.ohlcv_intervals, selectedProvider]);
  const overviewIntervalOptions = useMemo(() => {
    const profileIntervals = contractChartProfileIntervals(
      contract,
      "overview",
      DEFAULT_OVERVIEW_RESOURCE_INTERVALS
    );
    return profileIntervals.filter((item) => supportedResourceIntervals.includes(item));
  }, [contract, supportedResourceIntervals]);
  const professionalIntervalOptions = useMemo(() => {
    const profileIntervals = contractChartProfileIntervals(
      contract,
      "professional",
      RESOURCE_OHLCV_INTERVALS
    );
    return profileIntervals.filter((item) => supportedResourceIntervals.includes(item));
  }, [contract, supportedResourceIntervals]);
  const modeIntervalOptions = professionalMode
    ? professionalIntervalOptions
    : overviewIntervalOptions;
  const effectiveInterval =
    modeIntervalOptions.includes(interval)
      ? interval
      : modeIntervalOptions[0] ?? supportedResourceIntervals[0] ?? "1d";
  const chartLimit = chartLimitForInterval(effectiveInterval);
  const displayName = selectedInstrument?.display_name ?? fallbackInstrument?.displayName ?? requestedSymbol;
  const displaySymbol = selectedInstrument?.symbol ?? requestedSymbol;
  const chartStatusSource = `${displaySymbol || t("crypto.sidebar.commodity")} ${displayName || ""}`.trim();
  const dataStatusContextKey = resourceDataStatusContextKey(requestedSymbol);

  const loadData = useCallback(async () => {
    const requestId = ++dataRequestIdRef.current;
    setLoadState("loading");
    setSourceHealth(null);
    if (requestedSymbol) {
      setOhlcvBars([]);
      setDailyBars([]);
    }

    try {
      async function loadAndApply<T>(
        label: string,
        promise: Promise<T>,
        apply: (value: T) => void
      ) {
        const outcome = await loadOutcome(label, promise);
        if (dataRequestIdRef.current === requestId && outcome.ok) {
          apply(outcome.value);
        }
        return outcome;
      }

      const contractPromise = loadAndApply(
        t("crypto.resource.contract"),
        fetchJson<ResourceProviderContract>("/api/resource-market/provider-contract"),
        setContract
      );
      const instrumentsPromise = loadAndApply(
        t("crypto.resource.instruments"),
        fetchJson<ResourceInstrumentRead[]>("/api/resource-market/instruments"),
        setInstruments
      );
      const quotesPromise = loadAndApply(
        t("crypto.resource.marketData"),
        requestedSymbol
          ? fetchJson<ResourceQuoteSnapshot[]>("/api/resource-market/quotes/latest", {
              symbols: requestedSymbol,
              limit: 20,
            })
          : Promise.resolve([] as ResourceQuoteSnapshot[]),
        setQuotes
      );
      const allQuotesPromise = loadAndApply(
        t("crypto.resource.marketData"),
        fetchJson<ResourceQuoteSnapshot[]>("/api/resource-market/quotes/latest", {
          limit: 100,
        }),
        setAllQuotes
      );
      const ohlcvBarsPromise = loadAndApply(
        t("crypto.resource.kline"),
        requestedSymbol
          ? fetchJson<ResourceOhlcvBar[]>("/api/resource-market/ohlcv/latest", {
              symbols: requestedSymbol,
              interval: effectiveInterval,
              limit: chartLimit,
            })
          : Promise.resolve([] as ResourceOhlcvBar[]),
        setOhlcvBars
      );
      const dailyBarsPromise = loadAndApply(
        t("crypto.resource.kline"),
        requestedSymbol
          ? fetchJson<ResourceOhlcvBar[]>("/api/resource-market/ohlcv/latest", {
              symbols: requestedSymbol,
              interval: "1d",
              limit: 260,
            })
          : Promise.resolve([] as ResourceOhlcvBar[]),
        setDailyBars
      );
      const sourceHealthPromise = loadAndApply(
        t("crypto.resource.sourceHealth"),
        requestedSymbol
          ? fetchJson<ResourceSourceHealth>("/api/resource-market/source-health", {
              symbols: requestedSymbol,
              intervals: effectiveInterval,
              max_entries: 8,
            })
          : Promise.resolve(null),
        setSourceHealth
      );
      const subscriptionSettingsPromise = loadAndApply(
        t("crypto.resource.policy"),
        loadMarketDataSubscriptionSettings(),
        setSubscriptionSettings
      );

      const [
        contractResult,
        instrumentsResult,
        quotesResult,
        allQuotesResult,
        ohlcvBarsResult,
        dailyBarsResult,
        sourceHealthResult,
        subscriptionSettingsResult,
      ] = await Promise.all([
        contractPromise,
        instrumentsPromise,
        quotesPromise,
        allQuotesPromise,
        ohlcvBarsPromise,
        dailyBarsPromise,
        sourceHealthPromise,
        subscriptionSettingsPromise,
      ]);

      const criticalOutcomes = [
        contractResult,
        instrumentsResult,
        quotesResult,
        ohlcvBarsResult,
        sourceHealthResult,
      ];
      const loadFailures = loadFailureList([
        contractResult,
        instrumentsResult,
        quotesResult,
        allQuotesResult,
        ohlcvBarsResult,
        dailyBarsResult,
        sourceHealthResult,
        subscriptionSettingsResult,
      ]);

      if (criticalOutcomes.every((outcome) => !outcome.ok)) {
        throw loadFailures[0].error;
      }

      if (dataRequestIdRef.current !== requestId) return;

      if (loadFailures.length) {
        emitDataStatusEvent({
          market: "crypto",
          level: "warning",
          title: t("crypto.resource.loadPartial"),
          message: loadFailureMessage(t, "crypto.resource.loadPartialMessage", loadFailures),
          source: t("crypto.sidebar.commodity"),
          contextKey: dataStatusContextKey,
          contextLabel: chartStatusSource,
          dedupeKey: resourceDataStatusDedupeKey(requestedSymbol, effectiveInterval),
        });
      }
      setLoadState("success");
    } catch (error) {
      if (dataRequestIdRef.current !== requestId) return;
      emitDataStatusEvent({
        market: "crypto",
        level: "error",
        title: t("crypto.resource.loadFailed"),
        message: error instanceof Error ? error.message : t("crypto.resource.loadFailed"),
        source: t("crypto.sidebar.commodity"),
        contextKey: dataStatusContextKey,
        contextLabel: chartStatusSource,
        dedupeKey: resourceDataStatusDedupeKey(requestedSymbol, effectiveInterval),
      });
      setLoadState("error");
    }
  }, [chartLimit, chartStatusSource, dataStatusContextKey, effectiveInterval, requestedSymbol, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadData();
    }, 0);

    return () => window.clearTimeout(timer);
  }, [loadData]);

  useEffect(() => {
    if (interval === effectiveInterval) {
      return;
    }

    const timer = window.setTimeout(() => {
      setInterval(effectiveInterval);
    }, 0);

    return () => window.clearTimeout(timer);
  }, [effectiveInterval, interval]);

  useEffect(() => {
    function handleSubscriptionSettingsUpdated(event: Event) {
      const nextSettings = (event as CustomEvent<MarketDataSubscriptionSettingsRead>).detail;
      if (nextSettings) {
        setSubscriptionSettings(nextSettings);
      }
    }

    window.addEventListener(
      MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
      handleSubscriptionSettingsUpdated
    );
    return () =>
      window.removeEventListener(
        MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
        handleSubscriptionSettingsUpdated
      );
  }, []);

  const selectedQuote = latestQuote(quotes);
  const subscriptionKey = selectedInstrument?.key ?? resolvedKey;
  const subscriptionItem = useMemo(
    () => marketDataSubscriptionItem(subscriptionSettings, subscriptionKey),
    [subscriptionKey, subscriptionSettings]
  );
  const subscriptionMode = subscriptionItem?.mode ?? null;
  const healthEntries = useMemo(() => sourceHealth?.entries ?? [], [sourceHealth]);
  const healthSymbol = selectedInstrument?.symbol ?? requestedSymbol;
  const currentQuoteHealth = useMemo(() => {
    return healthEntries.find(
      (entry) => entry.resource === "quote" && entry.target === healthSymbol
    ) ?? null;
  }, [healthEntries, healthSymbol]);
  const currentOhlcvHealth = useMemo(() => {
    const target = `${healthSymbol}:${effectiveInterval}`;
    return healthEntries.find(
      (entry) => entry.resource === "ohlcv" && entry.target === target
    ) ?? null;
  }, [effectiveInterval, healthEntries, healthSymbol]);
  const healthIssue = healthEntries.find(resourceHealthEntryHasIssue);
  const ohlcvRefreshEnabled = !subscriptionItem || resourceSubscriptionAllowsManualRefresh(subscriptionItem);
  const ohlcvAutoRefreshEnabled = !subscriptionItem || resourceSubscriptionAllowsAutoRefresh(subscriptionItem);
  const ohlcvMissingDataRepairEnabled =
    !subscriptionItem || resourceSubscriptionAllowsMissingDataRepair(subscriptionItem);

  const chartData = useMemo<ChartPoint[]>(() => {
    const rowsByTime = new Map<string, ResourceOhlcvBar>();

    ohlcvBars
      .filter((row) => row.interval === effectiveInterval && row.close_price !== null)
      .forEach((row) => {
        const timeKey = resourceChartTimeKey(row, effectiveInterval);
        const existing = rowsByTime.get(timeKey);
        if (!existing || resourceRowFreshness(row) >= resourceRowFreshness(existing)) {
          rowsByTime.set(timeKey, row);
        }
      });

    return Array.from(rowsByTime.entries())
      .sort(([leftTime], [rightTime]) => sortableTimeValue(leftTime) - sortableTimeValue(rightTime))
      .map(([time, row]) => barToChartPoint(row, time));
  }, [effectiveInterval, ohlcvBars]);

  const latestChartPoint = chartData[chartData.length - 1] ?? null;
  const latestClose = selectedQuote?.last_price ?? latestChartPoint?.close ?? null;
  const priceChange = selectedQuote?.price_change ?? null;
  const priceChangePct = selectedQuote?.price_change_pct ?? null;
  const displayTime = selectedQuote?.event_time ?? selectedQuote?.fetched_at ?? latestChartPoint?.time ?? null;
  const currentIntervalLabel = t(`crypto.intervals.${effectiveInterval}`);
  const quoteFreshness = currentQuoteHealth
    ? `${resourceHealthStatusLabel(currentQuoteHealth.status, t)} / ${formatDurationSeconds(
        currentQuoteHealth.age_seconds,
        t
      )}`
    : "-";
  const quoteSession = resourceSessionStatusLabel(currentQuoteHealth?.session_status, t);
  const currentKlineCoverage = currentOhlcvHealth
    ? t("crypto.resource.klineCoverageValue", {
        rows: currentOhlcvHealth.row_count,
        interval: currentIntervalLabel,
      })
    : "-";
  const latestKlineBar = currentOhlcvHealth?.latest_fetched_at
    ? formatDateTimeShort(currentOhlcvHealth.latest_data_key, locale)
    : "-";
  const statusEventEntry =
    [currentQuoteHealth, currentOhlcvHealth].find(
      (entry): entry is ResourceSourceHealthEntry =>
        Boolean(entry && resourceHealthEntryHasIssue(entry))
    ) ?? currentOhlcvHealth ?? currentQuoteHealth;
  const lastHealthEvent = resourceLatestEventSummary(statusEventEntry, locale, t);
  const selectedQuotePollingEnabled = resourceSubscriptionAllowsQuotePolling(subscriptionItem);
  const selectedQuotePollingSeconds = resourceSelectedQuoteIntervalSeconds(subscriptionItem);
  const emptyChartTitle = loadState === "loading" || refreshing
    ? t("crypto.resource.loading")
    : t("crypto.resource.emptyChart");
  const emptyChartDetail = loadState === "loading"
    ? t("crypto.resource.loading")
    : refreshing
      ? t("crypto.resource.backfillingKline", { interval: currentIntervalLabel })
      : t("crypto.resource.emptyChartHint", { interval: currentIntervalLabel });
  const quoteBySymbol = useMemo(
    () => latestQuotesBySymbol([...allQuotes, ...quotes]),
    [allQuotes, quotes]
  );
  const dailyChartData = useMemo(() => dailyChartPointsFromBars(dailyBars), [dailyBars]);
  const latestDailyClose = dailyChartData[dailyChartData.length - 1]?.close ?? latestClose;
  const fiveDayBase = pointBeforeOffset(dailyChartData, 5)?.close ?? null;
  const oneMonthBase = pointBeforeOffset(dailyChartData, 21)?.close ?? null;
  const threeMonthBase = pointBeforeOffset(dailyChartData, 63)?.close ?? null;
  const ytdBase = ytdBasePoint(dailyChartData)?.close ?? null;
  const range20 = highLowStats(dailyChartData, 20, latestDailyClose);
  const range60 = highLowStats(dailyChartData, 60, latestDailyClose);
  const range260 = highLowStats(dailyChartData, 260, latestDailyClose);
  const intradayRangePct = pctChangeFromBase(
    selectedQuote?.high_price !== null &&
      selectedQuote?.high_price !== undefined &&
      selectedQuote?.low_price !== null &&
      selectedQuote?.low_price !== undefined
      ? selectedQuote.high_price - selectedQuote.low_price
      : null,
    latestClose
  );
  const atr14Pct = atrPct(dailyChartData, 14);
  const healthIssueCount = healthEntries.filter(resourceHealthEntryHasIssue).length;
  const dataViewTabs: Array<{
    key: ResourceDataView;
    label: string;
    detail: string;
    badge?: string | null;
  }> = [
    {
      key: "overview",
      label: "總覽",
      detail: "只顯示核心行情、交易時段與目前快照。",
    },
    {
      key: "move",
      label: "變化",
      detail: "整理多週期漲跌、區間位置與波動狀態。",
    },
    {
      key: "compare",
      label: "比較",
      detail: "用商品間比值觀察相對強弱與風險偏好線索。",
    },
    {
      key: "data",
      label: "資料",
      detail: "provider、合約、訂閱與 watch-only policy。",
    },
    {
      key: "health",
      label: "健康",
      detail: "來源健康、stale/error 與最近事件。",
      badge: healthIssueCount ? String(healthIssueCount) : null,
    },
  ];
  const activeDataViewDetail =
    dataViewTabs.find((tab) => tab.key === activeDataView)?.detail ?? "";
  const priceChangeCards: ResourceMetricCard[] = [
    {
      key: "day",
      label: "本次報價",
      value: `${formatSignedNumber(priceChange)} / ${formatPct(priceChangePct)}`,
      detail: formatDateTimeShort(displayTime, locale),
      valueClassName: valueTone(priceChangePct),
    },
    {
      key: "5d",
      label: "5 日",
      value: formatPct(pctChangeFromBase(latestDailyClose, fiveDayBase)),
      detail: fiveDayBase ? `基準 ${formatNumber(fiveDayBase)}` : null,
      valueClassName: valueTone(pctChangeFromBase(latestDailyClose, fiveDayBase)),
    },
    {
      key: "1m",
      label: "1 個月",
      value: formatPct(pctChangeFromBase(latestDailyClose, oneMonthBase)),
      detail: oneMonthBase ? `基準 ${formatNumber(oneMonthBase)}` : null,
      valueClassName: valueTone(pctChangeFromBase(latestDailyClose, oneMonthBase)),
    },
    {
      key: "3m",
      label: "3 個月",
      value: formatPct(pctChangeFromBase(latestDailyClose, threeMonthBase)),
      detail: threeMonthBase ? `基準 ${formatNumber(threeMonthBase)}` : null,
      valueClassName: valueTone(pctChangeFromBase(latestDailyClose, threeMonthBase)),
    },
    {
      key: "ytd",
      label: "YTD",
      value: formatPct(pctChangeFromBase(latestDailyClose, ytdBase)),
      detail: ytdBase ? `年初 ${formatNumber(ytdBase)}` : null,
      valueClassName: valueTone(pctChangeFromBase(latestDailyClose, ytdBase)),
    },
  ];
  const rangeCards: ResourceMetricCard[] = [
    {
      key: "20d",
      label: "20 日區間",
      value: range20 ? `${formatNumber(range20.low)} - ${formatNumber(range20.high)}` : "-",
      detail: range20 ? `位置 ${formatUnsignedPct(range20.position)}` : null,
    },
    {
      key: "60d",
      label: "60 日區間",
      value: range60 ? `${formatNumber(range60.low)} - ${formatNumber(range60.high)}` : "-",
      detail: range60 ? `位置 ${formatUnsignedPct(range60.position)}` : null,
    },
    {
      key: "52w",
      label: "近 52 週",
      value: range260 ? `${formatNumber(range260.low)} - ${formatNumber(range260.high)}` : "-",
      detail: range260 ? `位置 ${formatUnsignedPct(range260.position)}` : null,
    },
    {
      key: "atr14",
      label: "ATR 14",
      value: formatPct(atr14Pct),
      detail: "日 K 波動率",
    },
    {
      key: "intraday-range",
      label: "盤中振幅",
      value: formatPct(intradayRangePct),
      detail: `${formatNumber(selectedQuote?.low_price)} - ${formatNumber(selectedQuote?.high_price)}`,
    },
  ];
  const ratioCards: ResourceMetricCard[] = [
    {
      key: "gold-silver",
      label: "金銀比",
      value: formatNumber(quoteRatio(quoteBySymbol, "GC", "SI"), 2),
      detail: "GC / SI",
    },
    {
      key: "copper-gold",
      label: "銅金比",
      value: formatNumber(quoteRatio(quoteBySymbol, "HG", "GC"), 4),
      detail: "HG / GC",
    },
    {
      key: "wti-brent",
      label: "WTI / Brent",
      value: formatNumber(quoteRatio(quoteBySymbol, "CL", "BZ"), 4),
      detail: "CL / BZ",
    },
    {
      key: "oil-gas",
      label: "油氣比",
      value: formatNumber(quoteRatio(quoteBySymbol, "CL", "NG"), 2),
      detail: "CL / NG",
    },
  ];

  function renderEmptyChartState(className: string) {
    return (
      <div className={className}>
        <div className="max-w-xl">
          <div className="font-semibold text-omi-text">{emptyChartTitle}</div>
          <div className="mt-1 text-xs leading-5 text-omi-text-muted">
            {emptyChartDetail}
          </div>
        </div>
      </div>
    );
  }

  useEffect(() => {
    if (!requestedSymbol) return;

    setDataStatusFocus({
      market: "crypto",
      contextKey: dataStatusContextKey,
      label: chartStatusSource,
      source: t("crypto.sidebar.commodity"),
    });

    return () => clearDataStatusFocus(dataStatusContextKey);
  }, [chartStatusSource, dataStatusContextKey, requestedSymbol, t]);

  const loadLatestQuote = useCallback(async () => {
    if (!requestedSymbol) return;
    const nextQuotes = await fetchJson<ResourceQuoteSnapshot[]>(
      "/api/resource-market/quotes/latest",
      {
        symbols: requestedSymbol,
        limit: 20,
      }
    );
    setQuotes(nextQuotes);
  }, [requestedSymbol]);

  const refreshQuoteData = useCallback(async () => {
    if (!requestedSymbol) return;
    await requestJson<ResourceRefreshResult>(
      "/api/resource-market/quotes/refresh",
      { method: "POST" },
      { symbols: requestedSymbol },
      { timeoutMs: RESOURCE_QUOTE_REFRESH_TIMEOUT_MS }
    );
    await loadLatestQuote();
  }, [loadLatestQuote, requestedSymbol]);

  const refreshData = useCallback(async (options?: {
    silent?: boolean;
    reason?: ResourceOhlcvRefreshReason;
  }) => {
    if (!requestedSymbol || !ohlcvRefreshEnabled) return null;

    setRefreshing(true);
    const silent = options?.silent ?? false;
    const reason = options?.reason ?? "manual";
    const refreshIntervalLabel = t(`crypto.intervals.${effectiveInterval}`);
    if (silent && reason === "auto_empty") {
      emitDataStatusEvent({
        market: "crypto",
        level: "info",
        title: t("crypto.resource.refreshApprox"),
        message: t("crypto.resource.backfillingKline", { interval: refreshIntervalLabel }),
        source: chartStatusSource,
        contextKey: dataStatusContextKey,
        contextLabel: chartStatusSource,
        dedupeKey: resourceDataStatusDedupeKey(requestedSymbol, effectiveInterval),
      });
    }

    try {
      const result = await requestJson<ResourceRefreshResult>(
        "/api/resource-market/refresh",
        { method: "POST" },
        {
          symbols: requestedSymbol,
          intervals: refreshIntervalsForMode(effectiveInterval, professionalMode),
          limit: refreshLimitForMode(effectiveInterval, professionalMode),
        },
        { timeoutMs: RESOURCE_REFRESH_TIMEOUT_MS }
      );
      const shouldShowSuccess = reason === "manual" || reason === "auto_empty";
      const intervalResult = resultForOhlcvInterval(result, effectiveInterval);
      const intervalRefreshedCount = intervalResult
        ? numericResultField(intervalResult, "refreshed_count")
        : result.refreshed_count;
      const intervalErrorCount = intervalResult
        ? numericResultField(intervalResult, "error_count")
        : result.error_count;
      const intervalStatus = intervalResult
        ? stringResultField(intervalResult, "status")
        : result.status;
      const currentIntervalIssue =
        intervalErrorCount > 0 ||
        (reason === "auto_empty" && intervalRefreshedCount === 0);
      const eventLevel = result.error_count > 0 || currentIntervalIssue ? "warning" : "success";
      const intervalSummary = t("crypto.resource.chartHealthSummary", {
        interval: refreshIntervalLabel,
        rows: intervalRefreshedCount,
        status: intervalStatus || "-",
      });
      if (!silent || result.error_count > 0 || shouldShowSuccess) {
        const reasonLabel = resourceRefreshReasonLabel(reason, t);
        emitDataStatusEvent({
          market: "crypto",
          level: eventLevel,
          title: eventLevel === "warning"
            ? t("crypto.resource.refreshPartial")
            : t("crypto.resource.refreshComplete"),
          message: `${reasonLabel} / ${t("crypto.resource.refreshSummary", {
            status: result.status,
            refreshed: result.refreshed_count,
            skipped: result.skipped_count,
            errors: result.error_count,
          })} / ${intervalSummary}`,
          source: chartStatusSource,
          contextKey: dataStatusContextKey,
          contextLabel: chartStatusSource,
          dedupeKey: resourceDataStatusDedupeKey(requestedSymbol, effectiveInterval),
        });
      }
      await loadData();
      return result;
    } catch (error) {
      emitDataStatusEvent({
        market: "crypto",
        level: "error",
        title: t("crypto.resource.refreshFailed"),
        message: error instanceof Error ? error.message : t("crypto.resource.refreshFailed"),
        source: chartStatusSource,
        contextKey: dataStatusContextKey,
        contextLabel: chartStatusSource,
        dedupeKey: resourceDataStatusDedupeKey(requestedSymbol, effectiveInterval),
      });
      return null;
    } finally {
      setRefreshing(false);
    }
  }, [
    chartStatusSource,
    dataStatusContextKey,
    effectiveInterval,
    loadData,
    ohlcvRefreshEnabled,
    professionalMode,
    requestedSymbol,
    t,
  ]);

  useEffect(() => {
    if (
      subscriptionMode !== "on_select" ||
      !requestedSymbol ||
      !ohlcvAutoRefreshEnabled
    ) {
      return;
    }

    const refreshKey = [
      selectedInstrument?.key ?? resolvedKey,
      effectiveInterval,
      subscriptionSettings?.source ?? "unknown",
      subscriptionSettings?.version ?? "unknown",
    ].join(":");
    if (autoRefreshKeyRef.current === refreshKey) return;

    autoRefreshKeyRef.current = refreshKey;
    void refreshData({ silent: true, reason: "on_select" });
  }, [
    effectiveInterval,
    ohlcvAutoRefreshEnabled,
    refreshData,
    requestedSymbol,
    resolvedKey,
    selectedInstrument?.key,
    subscriptionMode,
    subscriptionSettings?.source,
    subscriptionSettings?.version,
  ]);

  useEffect(() => {
    if (
      loadState !== "success" ||
      !requestedSymbol ||
      refreshing
    ) {
      return;
    }
    if (typeof document !== "undefined" && document.visibilityState !== "visible") return;

    const reason = resourceChartRefreshReason(chartData, currentOhlcvHealth);
    if (!reason) return;
    const refreshAllowed =
      reason === "auto_empty" ? ohlcvMissingDataRepairEnabled : ohlcvAutoRefreshEnabled;
    if (!refreshAllowed) return;

    const lockKey = [
      selectedInstrument?.key ?? resolvedKey,
      effectiveInterval,
      reason,
    ].join(":");
    const now = Date.now();
    const throttleMs = reason === "auto_empty"
      ? RESOURCE_AUTO_REFRESH_RETRY_BACKOFF_MS
      : Math.max(
          RESOURCE_AUTO_REFRESH_RETRY_BACKOFF_MS,
          RESOURCE_AUTO_REFRESH_STALE_MS_BY_INTERVAL[effectiveInterval]
        );
    const effectiveThrottleMs = currentOhlcvHealth?.recent_error_count
      ? Math.max(throttleMs, RESOURCE_AUTO_REFRESH_ERROR_BACKOFF_MS)
      : throttleMs;
    const lastAttemptAt = chartAutoRefreshAttemptsRef.current[lockKey] ?? 0;
    if (chartAutoRefreshInFlightRef.current || now - lastAttemptAt < effectiveThrottleMs) return;

    chartAutoRefreshAttemptsRef.current[lockKey] = now;
    chartAutoRefreshInFlightRef.current = lockKey;
    void refreshData({ silent: true, reason }).finally(() => {
      if (chartAutoRefreshInFlightRef.current === lockKey) {
        chartAutoRefreshInFlightRef.current = null;
      }
    });
  }, [
    chartData,
    currentOhlcvHealth,
    effectiveInterval,
    loadState,
    ohlcvAutoRefreshEnabled,
    ohlcvMissingDataRepairEnabled,
    refreshData,
    refreshing,
    requestedSymbol,
    resolvedKey,
    selectedInstrument?.key,
  ]);

  useEffect(() => {
    if (!selectedQuotePollingEnabled || !requestedSymbol) return;

    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (quotePollingRef.current) return;

      quotePollingRef.current = true;
      void refreshQuoteData()
        .catch(() => {
          // Keep quote polling quiet; manual refresh and full load surface errors.
        })
        .finally(() => {
          quotePollingRef.current = false;
        });
    }, selectedQuotePollingSeconds * 1000);

    return () => window.clearInterval(timer);
  }, [
    refreshQuoteData,
    requestedSymbol,
    selectedQuotePollingEnabled,
    selectedQuotePollingSeconds,
  ]);

  function applyIndicatorTemplate(templateKey: IndicatorTemplateKey) {
    const template = indicatorTemplates.find((item) => item.key === templateKey);
    if (!template) return;
    setChartIndicators(template.indicators);
    setActiveIndicatorTemplate(template.key);
  }

  function toggleChartIndicator(key: IndicatorKey) {
    setChartIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
    setActiveIndicatorTemplate(null);
  }

  const chartDrawingInstrumentKey = selectedInstrument?.key ?? resolvedKey;
  const chartDrawingKey = chartDrawingStorageKey(chartDrawingInstrumentKey, effectiveInterval);
  const storedChartDrawings = useMemo(
    () => loadChartDrawings(chartDrawingKey),
    [chartDrawingKey]
  );
  const chartDrawings =
    chartDrawingState.key === chartDrawingKey ? chartDrawingState.drawings : storedChartDrawings;
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
  const professionalDrawingContext = useMemo(
    () => ({
      market: "RESOURCE",
      symbol: chartDrawingInstrumentKey,
      timeframe: effectiveInterval,
    }),
    [chartDrawingInstrumentKey, effectiveInterval]
  );

  const queueChartDrawingRemoteSave = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave: string | null
  ) => {
    if (typeof window === "undefined") return;

    const path = chartDrawingApiPath("RESOURCE", chartDrawingInstrumentKey, effectiveInterval);
    const payload = buildChartDrawingSnapshotPayload({
      drawings: drawingsToSave,
      market: "RESOURCE",
      selectedDrawingId: selectedDrawingIdToSave,
      source: "frontend.resource_professional_chart",
      stockName: `${displaySymbol} ${displayName}`.trim(),
      symbol: chartDrawingInstrumentKey,
      timeframe: effectiveInterval,
      timeMode: chartTimeMode(effectiveInterval),
    });

    if (chartDrawingSyncTimerRef.current) {
      window.clearTimeout(chartDrawingSyncTimerRef.current);
    }

    chartDrawingSyncTimerRef.current = window.setTimeout(() => {
      void requestJson<ChartDrawingSnapshotRead>(path, {
        method: "PUT",
        body: JSON.stringify(payload),
      }).catch(() => {
        // Best-effort server sync. Local chart drawings remain available.
      });
    }, chartDrawingSyncDelayMs);
  }, [chartDrawingInstrumentKey, displayName, displaySymbol, effectiveInterval]);

  const storeChartDrawings = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave = activeSelectedChartDrawingId
  ) => {
    chartDrawingLocalRevisionRef.current += 1;
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
    if (!professionalMode) return;
    if (chartDrawingState.key === chartDrawingKey) return;

    let cancelled = false;
    const loadRevision = chartDrawingLocalRevisionRef.current;
    const hasLocalSnapshot = hasChartDrawingSnapshot(chartDrawingKey);
    const localDrawings = loadChartDrawings(chartDrawingKey);
    const normalizedLocalSelection = normalizeChartDrawingSelection(
      localDrawings,
      activeSelectedChartDrawingId
    );

    if (hasLocalSnapshot && localDrawings.length === 0) {
      return () => {
        cancelled = true;
      };
    }

    if (localDrawings.length > 0) {
      queueChartDrawingRemoteSave(localDrawings, normalizedLocalSelection);
      return () => {
        cancelled = true;
      };
    }

    async function loadRemoteChartDrawings() {
      try {
        const snapshot = await fetchJson<ChartDrawingSnapshotRead>(
          chartDrawingApiPath("RESOURCE", chartDrawingInstrumentKey, effectiveInterval)
        );

        if (cancelled || chartDrawingLocalRevisionRef.current !== loadRevision) return;

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
        // Missing remote snapshot means this resource chart has not been saved server-side yet.
      }
    }

    void loadRemoteChartDrawings();

    return () => {
      cancelled = true;
    };
  }, [
    activeSelectedChartDrawingId,
    chartDrawingInstrumentKey,
    chartDrawingState.key,
    chartDrawingKey,
    effectiveInterval,
    professionalMode,
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

    const nextSnapshot = chartDrawingHistory.future[0];
    if (!nextSnapshot) return;

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: [
        ...chartDrawingHistory.past,
        createChartDrawingSnapshot(chartDrawings, activeSelectedChartDrawingId),
      ].slice(-50),
      future: chartDrawingHistory.future.slice(1),
    });
    storeChartDrawings(nextSnapshot.drawings, nextSnapshot.selectedDrawingId);
    setSelectedChartDrawingId(nextSnapshot.selectedDrawingId);
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
    if (!window.confirm("清除這個商品圖表的所有畫線？")) return;

    updateChartDrawings([]);
    setSelectedChartDrawingId(null);
  }

  useEffect(() => {
    if (!professionalMode) return;

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
    professionalMode,
    redoChartDrawing,
    undoChartDrawing,
  ]);

  function closeProfessionalMode() {
    setIndicatorMenuOpen(false);
    setChartDrawingTool("cursor");
    setProfessionalMode(false);
    if (!overviewIntervalOptions.includes(effectiveInterval)) {
      setInterval(overviewIntervalOptions[0] ?? "1m");
    }
  }

  if (professionalMode) {
    return (
      <ProfessionalChartPanel
        title={`${displaySymbol} ${displayName}`}
        priceSummary={
          <div className={["flex items-baseline gap-2", valueTone(priceChangePct)].join(" ")}>
            <PriceUpdatePulse
              value={latestClose}
              direction={priceChangePct}
              resetKey={`${displaySymbol}:resource-professional:${effectiveInterval}`}
              className="text-2xl font-bold leading-none tracking-normal tabular-nums"
            >
              {formatNumber(latestClose)}
            </PriceUpdatePulse>
            <span className="text-sm font-semibold tabular-nums">
              {formatSignedNumber(priceChange)}
            </span>
            <span className="text-sm font-semibold tabular-nums">
              ({formatPct(priceChangePct)})
            </span>
          </div>
        }
        timeframeOptions={professionalIntervalOptions.map((item) => ({
          key: item,
          label: t(`crypto.intervals.${item}`),
        }))}
        timeframe={effectiveInterval}
        onTimeframeChange={(nextInterval) => {
          setIndicatorMenuOpen(false);
          setInterval(nextInterval);
        }}
        chartStyle={professionalChartStyle}
        onChartStyleChange={setProfessionalChartStyle}
        indicatorMenuOpen={indicatorMenuOpen}
        onToggleIndicatorMenu={() => setIndicatorMenuOpen((value) => !value)}
        onCloseIndicatorMenu={() => setIndicatorMenuOpen(false)}
        indicatorMenu={
          <TechnicalIndicatorMenu
            indicators={chartIndicators}
            activeTemplate={activeIndicatorTemplate}
            onApplyTemplate={applyIndicatorTemplate}
            onToggleIndicator={toggleChartIndicator}
            groups={professionalIndicatorCategoryGroups}
            className="w-[28rem]"
          />
        }
        onClose={closeProfessionalMode}
        drawingToolbarStart={
          <>
            <button
              type="button"
              className="h-7 px-2 text-xs font-semibold text-omi-text-muted transition hover:bg-omi-surface hover:text-omi-text-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
              onClick={() => void loadData()}
              disabled={loadState === "loading" || refreshing}
            >
              {t("crypto.resource.reload")}
            </button>
            <button
              type="button"
              className="h-7 px-2 text-xs font-semibold text-omi-accent transition hover:bg-omi-surface hover:text-omi-text-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
              onClick={() => void refreshData()}
              disabled={refreshing || !requestedSymbol || !ohlcvRefreshEnabled}
            >
              {refreshing ? t("crypto.resource.refreshing") : t("crypto.resource.refreshApprox")}
            </button>
          </>
        }
        chartReady={chartData.length > 0}
        emptyState={
          renderEmptyChartState(
            "flex h-[640px] items-center justify-center border-t border-omi-border-subtle px-4 text-center text-sm"
          )
        }
        chartData={chartData}
        label={`${displaySymbol} ${displayName}`}
        timeMode={chartTimeMode(effectiveInterval)}
        showMovingAverages={chartIndicators.ma}
        indicators={chartIndicators}
        indicatorParameters={defaultIndicatorParameters}
        volumePanelLabel={t("crypto.resource.volume")}
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
    );
  }

  return (
    <section className="grid w-full grid-cols-1 items-start justify-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]">
      <div className="min-w-0 self-start space-y-4">
        <section className="border border-omi-border-subtle bg-omi-surface">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("crypto.kline.sectionTitle")}
              </div>
              <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
                {displaySymbol} {displayName}
              </h2>
              <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-sm text-omi-text-muted">
                <span>{selectedInstrument?.exchange ?? "-"}</span>
                <span>/</span>
                <span>{selectedInstrument?.quote_asset ?? "-"}</span>
                <span>/</span>
                <span>{selectedInstrument?.provider_symbol ?? "-"}</span>
                <span>/</span>
                <span>{formatDateTimeShort(displayTime, locale)}</span>
                <span>/</span>
                <span>{t("crypto.kline.bars", { count: chartData.length })}</span>
              </div>
            </div>

            <div className="flex flex-wrap items-start justify-end gap-5">
              <div className={`text-right ${valueTone(priceChangePct)}`}>
                <PriceUpdatePulse
                  value={latestClose}
                  direction={priceChangePct}
                  resetKey={`${displaySymbol}:${effectiveInterval}`}
                  className="text-3xl font-bold leading-none tracking-normal tabular-nums"
                >
                  {formatNumber(latestClose)}
                </PriceUpdatePulse>
                <div className="text-base font-semibold tabular-nums">
                  {formatSignedNumber(priceChange)} / {formatPct(priceChangePct)}
                </div>
              </div>

              <div className="flex flex-col items-end gap-2">
                <div className="flex border border-omi-border-subtle bg-omi-surface-subtle p-1">
                  {overviewIntervalOptions.map((item) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => {
                        setInterval(item);
                        setIndicatorMenuOpen(false);
                      }}
                      className={[
                        "h-8 min-w-12 px-3 text-sm font-semibold transition",
                        effectiveInterval === item
                          ? "omi-timeframe-tab-active"
                          : "text-omi-text-muted hover:bg-omi-surface",
                      ].join(" ")}
                    >
                      {overviewIntervalLabel(item, t)}
                    </button>
                  ))}
                </div>

                <div className="flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    className="h-8 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text-muted transition hover:border-omi-accent hover:text-omi-accent disabled:cursor-not-allowed disabled:opacity-60"
                    onClick={() => void loadData()}
                    disabled={loadState === "loading" || refreshing}
                  >
                    {loadState === "loading" ? t("crypto.resource.loading") : t("crypto.resource.reload")}
                  </button>
                  <button
                    type="button"
                    className="h-8 border border-omi-accent-border bg-omi-accent-soft px-3 text-sm font-semibold text-omi-accent transition hover:border-omi-accent hover:bg-omi-surface-subtle disabled:cursor-not-allowed disabled:opacity-60"
                    onClick={() => void refreshData()}
                    disabled={refreshing || !requestedSymbol || !ohlcvRefreshEnabled}
                  >
                    {refreshing ? t("crypto.resource.refreshing") : t("crypto.resource.refreshApprox")}
                  </button>
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className={[
                        "h-8 border px-3 text-sm font-semibold transition",
                        indicatorMenuOpen
                          ? "border-omi-accent bg-omi-accent-soft text-omi-accent"
                          : "border-omi-border bg-omi-surface text-omi-text-muted hover:border-omi-accent hover:text-omi-accent",
                      ].join(" ")}
                    >
                      {t("crypto.kline.indicators")}
                    </button>
                    {indicatorMenuOpen ? (
                      <TechnicalIndicatorMenu
                        indicators={chartIndicators}
                        activeTemplate={activeIndicatorTemplate}
                        onApplyTemplate={applyIndicatorTemplate}
                        onToggleIndicator={toggleChartIndicator}
                        className="w-[26rem]"
                      />
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className="h-8 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text-muted transition hover:border-omi-accent hover:text-omi-accent"
                    onClick={() => {
                      setIndicatorMenuOpen(false);
                      setProfessionalMode(true);
                    }}
                  >
                    {t("crypto.kline.expand")}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="px-3 py-3">
            {chartData.length > 0 ? (
              <StockKLineChart
                chartData={chartData}
                label={`${displaySymbol} ${displayName}`}
                indicators={chartIndicators}
                indicatorParameters={defaultIndicatorParameters}
                revealKey={`resource-${displaySymbol}-${effectiveInterval}-${chartData.length}`}
                volumePanelLabel={t("crypto.resource.volume")}
                volumeTooltipLabel={t("crypto.resource.volume")}
                volumeValueFormatter={formatVolume}
              />
            ) : (
              renderEmptyChartState(
                "flex h-[420px] items-center justify-center border border-dashed border-omi-border-subtle bg-omi-surface-subtle px-4 text-center text-sm"
              )
            )}
          </div>
        </section>
      </div>

      <aside className="min-w-0 space-y-4">
        <section className="border border-omi-border-subtle bg-omi-surface">
          <div className="flex items-start justify-between gap-4 px-5 py-4">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("crypto.resource.marketData")}
              </div>
              <h3 className="mt-1 truncate text-xl font-bold text-omi-text-strong">
                {displayName}
              </h3>
              <div className="mt-1 truncate text-sm text-omi-text-muted">
                {selectedInstrument?.exchange ?? "-"} / {selectedInstrument?.quote_asset ?? "-"} /{" "}
                {selectedInstrument?.provider_symbol ?? "-"}
              </div>
            </div>
            <StatusPill
              label={providerStatusLabel(selectedInstrument?.provider_status, t)}
              status={selectedInstrument?.provider_status ?? "provider_pending"}
            />
          </div>
        </section>

        <section className="border border-omi-border-subtle bg-omi-surface">
          <div className="grid grid-cols-5 border-b border-omi-border-subtle">
            {dataViewTabs.map((tab) => {
              const active = tab.key === activeDataView;
              return (
                <button
                  key={tab.key}
                  type="button"
                  className={[
                    "omi-data-tab flex min-h-12 min-w-0 items-center justify-center gap-2 border-r border-omi-border-subtle px-2 py-2 text-sm font-semibold transition last:border-r-0",
                    active
                      ? "omi-data-tab-active bg-omi-surface-subtle text-omi-text-strong"
                      : "text-omi-text-muted hover:bg-omi-surface-subtle hover:text-omi-text",
                  ].join(" ")}
                  onClick={() => setActiveDataView(tab.key)}
                >
                  <span className="truncate">{tab.label}</span>
                  {tab.badge ? (
                    <span className="shrink-0 border border-omi-warning/40 px-1.5 py-0.5 text-[10px] tabular-nums text-omi-warning">
                      {tab.badge}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
          <div className="px-4 py-2 text-xs text-omi-text-muted">
            {activeDataViewDetail}
          </div>
        </section>

        {activeDataView === "overview" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <ResourcePanelHeader
              title={t("crypto.resource.marketData")}
              subtitle={`${displaySymbol} / ${subscriptionModeLabel(subscriptionItem, t)}`}
            />
            <ResourceMetricGrid
              items={[
                {
                  key: "last",
                  label: t("crypto.resource.last"),
                  value: formatNumber(latestClose),
                  detail: formatDateTimeShort(displayTime, locale),
                  valueClassName: valueTone(priceChangePct),
                },
                {
                  key: "change",
                  label: t("crypto.resource.change"),
                  value: `${formatSignedNumber(priceChange)} / ${formatPct(priceChangePct)}`,
                  detail: currentIntervalLabel,
                  valueClassName: valueTone(priceChangePct),
                },
                {
                  key: "range",
                  label: `${t("crypto.resource.low")} / ${t("crypto.resource.high")}`,
                  value: `${formatNumber(selectedQuote?.low_price)} - ${formatNumber(selectedQuote?.high_price)}`,
                  detail: `open ${formatNumber(selectedQuote?.open_price)}`,
                },
                {
                  key: "volume",
                  label: t("crypto.resource.volume"),
                  value: formatVolume(selectedQuote?.volume),
                  detail: quoteSession,
                },
              ]}
            />
            <div className="px-4 py-3 text-xs text-omi-text-muted">
              {t("crypto.resource.klineCoverage")}: {currentKlineCoverage} /{" "}
              {t("crypto.resource.quoteFreshness")}: {quoteFreshness}
            </div>
          </section>
        ) : null}

        {activeDataView === "move" ? (
          <>
            <section className="border border-omi-border-subtle bg-omi-surface">
              <ResourcePanelHeader title="價格變化" subtitle={`${displaySymbol} / 日線快取`} />
              <ResourceMetricGrid items={priceChangeCards} />
            </section>
            <section className="border border-omi-border-subtle bg-omi-surface">
              <ResourcePanelHeader title="區間與波動" subtitle={`${dailyChartData.length} 筆日線`} />
              <ResourceMetricGrid items={rangeCards} />
            </section>
          </>
        ) : null}

        {activeDataView === "compare" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <ResourcePanelHeader title="商品比較" subtitle="相對比值" />
            <ResourceMetricGrid items={ratioCards} />
            <div className="px-4 py-3 text-xs leading-5 text-omi-text-muted">
              比值用本機最新商品報價計算，只作相對強弱與風險偏好 context；缺報價時會顯示 -。
            </div>
          </section>
        ) : null}

        {activeDataView === "data" ? (
          <>
            <section className="border border-omi-border-subtle bg-omi-surface">
              <ResourcePanelHeader title={t("crypto.resource.dataCoverage")} subtitle={currentKlineCoverage} />
              <div className="divide-y divide-omi-border-subtle text-sm">
                <MetricRow label={t("crypto.resource.quoteFreshness")} value={quoteFreshness} />
                <MetricRow label={t("crypto.resource.session")} value={quoteSession} />
                <MetricRow label={t("crypto.resource.klineCoverage")} value={currentKlineCoverage} />
                <MetricRow label={t("crypto.resource.latestBar")} value={latestKlineBar} />
                <MetricRow
                  label={t("crypto.resource.eventTime")}
                  value={formatDateTimeShort(selectedQuote?.event_time, locale)}
                />
                <MetricRow
                  label={t("crypto.resource.fetchedAt")}
                  value={formatDateTimeShort(selectedQuote?.fetched_at, locale)}
                />
                <MetricRow label={t("crypto.resource.lastEvent")} value={lastHealthEvent} />
                <MetricRow label={t("crypto.resource.provider")} value={selectedInstrument?.provider ?? "-"} />
                <MetricRow
                  label={t("crypto.resource.providerSymbol")}
                  value={selectedInstrument?.provider_symbol ?? "-"}
                />
                <MetricRow label={t("crypto.resource.exchange")} value={selectedInstrument?.exchange ?? "-"} />
                <MetricRow label={t("crypto.resource.quoteAsset")} value={selectedInstrument?.quote_asset ?? "-"} />
              </div>
            </section>
            <section className="border border-omi-border-subtle bg-omi-surface">
              <ResourcePanelHeader
                title={t("crypto.resource.contract")}
                subtitle={contract?.kind ?? "resource_market_contract"}
              />
              <div className="space-y-3 px-5 py-4 text-sm text-omi-text-muted">
                <div className="flex flex-wrap gap-2">
                  <StatusPill
                    label={
                      selectedInstrument?.tradable
                        ? t("crypto.resource.tradable")
                        : t("crypto.resource.notTradable")
                    }
                    status={selectedInstrument?.tradable ? "ok" : "disabled"}
                  />
                  <StatusPill
                    label={
                      selectedInstrument?.trade_candidate
                        ? t("crypto.resource.tradeCandidate")
                        : t("crypto.resource.watchOnly")
                    }
                    status={selectedInstrument?.trade_candidate ? "ok" : "disabled"}
                  />
                </div>
                <p className="leading-5">{selectedInstrument?.role ?? t("crypto.resource.noContract")}</p>
                <p className="leading-5">{t("crypto.resource.executionDisabled")}</p>
                <p className="leading-5">{t("crypto.resource.aiExecutionDisabled")}</p>
              </div>
            </section>
            <section className="border border-omi-border-subtle bg-omi-surface">
              <ResourcePanelHeader
                title={t("crypto.resource.policy")}
                subtitle={subscriptionModeLabel(subscriptionItem, t)}
              />
              <div className="space-y-2 px-5 py-4 text-sm text-omi-text-muted">
                <p className="leading-5">
                  {subscriptionSettings?.source ?? t("crypto.market.subscriptionSource.loading")}
                </p>
                <p className="leading-5">{t("crypto.resource.cacheOnlyNote")}</p>
                {contract?.notes.slice(0, 2).map((note) => (
                  <p key={note} className="leading-5">
                    {note}
                  </p>
                ))}
              </div>
            </section>
          </>
        ) : null}

        {activeDataView === "health" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <ResourcePanelHeader
              title={t("crypto.resource.sourceHealth")}
              subtitle={sourceHealth ? formatDateTimeShort(sourceHealth.generated_at, locale) : "-"}
              action={
                <StatusPill
                  label={
                    healthIssue
                      ? resourceHealthStatusLabel(healthIssue.status, t)
                      : t("crypto.market.status.ok")
                  }
                  status={healthIssue?.status ?? "ok"}
                />
              }
            />
            <div className="grid grid-cols-3 border-b border-omi-border-subtle text-center text-xs">
              <HealthStat
                label={t("crypto.market.status.ok")}
                value={sourceHealth?.summary.ok_count ?? 0}
              />
              <HealthStat
                label={t("crypto.market.status.stale")}
                value={sourceHealth?.summary.stale_count ?? 0}
              />
              <HealthStat
                label={t("crypto.resource.healthErrors")}
                value={sourceHealth?.summary.error_count ?? 0}
              />
            </div>
            <div className="max-h-[320px] overflow-y-auto">
              {healthEntries.length > 0 ? (
                healthEntries.slice(0, 8).map((entry) => (
                  <div
                    key={`${entry.resource}-${entry.provider}-${entry.target}`}
                    className="grid grid-cols-[minmax(0,1fr)_72px] gap-3 border-b border-omi-border-subtle px-3 py-2 text-xs last:border-b-0"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-omi-text">
                        {entry.resource} {resourceHealthEntryLabel(entry)}
                      </div>
                      <div className="truncate text-omi-text-muted">
                        {entry.provider} / {resourceHealthEntryDetail(entry, locale, t)}
                      </div>
                    </div>
                    <div
                      className={[
                        "self-center border px-2 py-1 text-center font-semibold",
                        statusClass(entry.status),
                      ].join(" ")}
                    >
                      {resourceHealthStatusLabel(entry.status, t)}
                    </div>
                  </div>
                ))
              ) : (
                <div className="px-3 py-4 text-center text-xs text-omi-text-muted">
                  {t("crypto.resource.healthNoEntries")}
                </div>
              )}
            </div>
          </section>
        ) : null}
      </aside>
    </section>
  );
}

function StatusPill({ label, status }: { label: string; status: string }) {
  return (
    <span
      className={[
        "inline-flex border px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]",
        statusClass(status),
      ].join(" ")}
    >
      {label}
    </span>
  );
}

function HealthStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="border-r border-omi-border-subtle px-3 py-2 last:border-r-0">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-omi-text-muted">
        {label}
      </div>
      <div className="mt-1 text-lg font-black tabular-nums text-omi-text-strong">
        {value}
      </div>
    </div>
  );
}

function ResourcePanelHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 border-b border-omi-border-subtle px-4 py-3">
      <h2 className="shrink-0 text-sm font-bold text-omi-text-strong">{title}</h2>
      <div className="flex min-w-0 items-center justify-end gap-2">
        <span className="min-w-0 truncate text-right text-xs text-omi-text-muted">{subtitle}</span>
        {action}
      </div>
    </div>
  );
}

function ResourceMetricGrid({ items }: { items: ResourceMetricCard[] }) {
  return (
    <div className="grid border-b border-omi-border-subtle sm:grid-cols-2">
      {items.map((item) => (
        <div
          key={item.key}
          className="min-w-0 border-b border-r border-omi-border-subtle px-4 py-3 even:border-r-0 sm:[&:nth-last-child(-n+2)]:border-b-0"
        >
          <div className="truncate text-xs font-semibold uppercase text-omi-text-muted">{item.label}</div>
          <div
            className={[
              "mt-1 truncate text-xl font-bold tabular-nums text-omi-text-strong",
              item.valueClassName,
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {item.value}
          </div>
          {item.detail ? (
            <div className="mt-1 truncate text-xs text-omi-text-muted">{item.detail}</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function MetricRow({
  label,
  value,
  strong = false,
  valueClassName,
}: {
  label: string;
  value: string;
  strong?: boolean;
  valueClassName?: string;
}) {
  return (
    <div className="grid grid-cols-[minmax(120px,42%)_minmax(0,1fr)] gap-3 px-5 py-3">
      <span className="text-omi-text-muted">{label}</span>
      <span
        className={[
          "min-w-0 truncate text-right tabular-nums",
          strong ? "text-lg font-black text-omi-text-strong" : "font-semibold text-omi-text",
          valueClassName,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {value}
      </span>
    </div>
  );
}

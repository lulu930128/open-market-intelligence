"use client";

import type { ChartDrawing, ChartDrawingTool } from "@/components/LightweightKLineChart";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
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
import { buildApiUrl, fetchJson, requestJson } from "@/lib/api";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import {
  cryptoSubscriptionResourceEnabled,
  type MarketDataSubscriptionSettingsRead,
} from "@/lib/marketDataSubscriptions";
import {
  CRYPTO_KLINE_INSTRUMENTS,
  cryptoInstrumentsForBase,
  defaultCryptoInstrumentKeyForBase,
  type CryptoBaseAsset,
  type CryptoKLineInstrument,
  type CryptoProvider,
} from "@/types/cryptoMarket";
import type { ChartDrawingSnapshotRead, ChartPoint } from "@/types/market";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type CryptoInterval = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1d" | "1w" | "1M";
type CryptoOhlcvRefreshReason = "manual" | "auto_empty" | "auto_stale" | "auto_poll";
type SummaryTimeframe = "today" | "daily" | "weekly" | "monthly";
type VolumeMetric = "base" | "quote";

type CryptoOhlcvBar = {
  provider: string;
  exchange: string;
  symbol: string;
  provider_symbol: string;
  base_asset: string;
  quote_asset: string;
  instrument_type: string;
  interval: string;
  bar_time: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  base_volume: number | null;
  quote_volume: number | null;
  fetched_at: string;
};

type CryptoRealtimeLatest = {
  provider: string;
  resource: string;
  symbol: string;
  provider_symbol: string;
  instrument_type: string;
  event_time: string | null;
  received_at: string;
  feed_lag_ms: number | null;
  last_message_age_ms: number;
  stale: boolean;
  sequence: number | null;
  data: Record<string, unknown>;
};

type CryptoRealtimeStreamPayload = {
  kind: string;
  generated_at: string;
  rows: CryptoRealtimeLatest[];
};

type LiveChartUpdate = {
  provider: string;
  symbol: string;
  instrumentType: string;
  resource: string;
  priceResource: string;
  interval: CryptoInterval;
  time: string;
  close: number;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  tradeValue: number | null;
  receivedAt: string;
  sequence: number | null;
  lastMessageAgeMs: number;
};

const OHLCV_REFRESH_LIMIT_MAX = 1000;
const CHART_LIMIT_BY_INTERVAL: Record<CryptoInterval, number> = {
  "1m": 4320,
  "5m": 1728,
  "15m": 2016,
  "30m": 2016,
  "1h": 2160,
  "4h": 2160,
  "1d": 2190,
  "1w": 1560,
  "1M": 720,
};
const SUMMARY_TIMEFRAME_OPTIONS: Array<{
  key: SummaryTimeframe;
  interval: CryptoInterval;
}> = [
  { key: "today", interval: "1m" },
  { key: "daily", interval: "1d" },
  { key: "weekly", interval: "1w" },
  { key: "monthly", interval: "1M" },
];
const PROFESSIONAL_INTERVAL_OPTIONS: Array<{ interval: CryptoInterval }> = [
  { interval: "1m" },
  { interval: "5m" },
  { interval: "15m" },
  { interval: "30m" },
  { interval: "1h" },
  { interval: "4h" },
  { interval: "1d" },
  { interval: "1w" },
  { interval: "1M" },
];

const cryptoChartIndicators: IndicatorSettings = {
  ...defaultIndicators,
  ma: true,
  volume: true,
  vwap: true,
  macd: false,
  rsi: false,
  signals: false,
};
const AUTO_REFRESH_STALE_MS_BY_INTERVAL: Record<CryptoInterval, number> = {
  "1m": 30_000,
  "5m": 120_000,
  "15m": 300_000,
  "30m": 600_000,
  "1h": 1_200_000,
  "4h": 3_600_000,
  "1d": 21_600_000,
  "1w": 86_400_000,
  "1M": 86_400_000,
};
const AUTO_REFRESH_RETRY_BACKOFF_MS = 60_000;
const LIVE_OHLCV_REFRESH_INTERVALS = new Set<CryptoInterval>(["1m", "5m", "15m", "30m"]);
const LIVE_OHLCV_REFRESH_MIN_INTERVAL_MS = 10_000;
const LIVE_CHART_RENDER_INTERVALS = new Set<CryptoInterval>([
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "4h",
  "1d",
  "1w",
  "1M",
]);
const LIVE_CHART_RENDER_INTERVAL_MS = 1_000;
const LIVE_CHART_STREAM_WATCHDOG_MS = 2_500;
const CRYPTO_DISPLAY_TIME_ZONE = "Asia/Taipei";
const CRYPTO_TAIPEI_CHART_TIME_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: CRYPTO_DISPLAY_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
const LIVE_CHART_INTERVAL_MS_BY_INTERVAL: Partial<Record<CryptoInterval, number>> = {
  "1m": 60_000,
  "5m": 5 * 60_000,
  "15m": 15 * 60_000,
  "30m": 30 * 60_000,
  "1h": 60 * 60_000,
  "4h": 4 * 60 * 60_000,
  "1d": 24 * 60 * 60_000,
};

function formatNumber(value: number | null | undefined, maximumFractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("en-US", {
    maximumFractionDigits,
  });
}

function formatCryptoVolume(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const absValue = Math.abs(value);
  if (absValue >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`;
  if (absValue >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (absValue >= 1_000) return `${(value / 1_000).toFixed(2)}K`;
  return formatNumber(value, absValue < 1 ? 6 : 4);
}

function formatCryptoPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const absValue = Math.abs(value);
  return formatNumber(value, absValue >= 1_000 ? 2 : 6);
}

function formatSignedNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return `${value > 0 ? "+" : ""}${formatCryptoPrice(value)}`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return `${value > 0 ? "+" : ""}${formatNumber(value, 2)}%`;
}

function parseCryptoUtcDateTime(value: string | null | undefined) {
  const trimmed = value?.trim();
  if (!trimmed) return null;

  const normalized = trimmed.includes("T")
    ? trimmed
    : trimmed.includes(" ")
      ? trimmed.replace(" ", "T")
      : `${trimmed}T00:00:00`;
  const hasExplicitZone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(normalized);
  const parsed = new Date(hasExplicitZone ? normalized : `${normalized}Z`);

  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDateTime(value: string | null | undefined, locale: string) {
  const date = parseCryptoUtcDateTime(value);
  if (!date) return "-";

  return date.toLocaleString(locale, {
    timeZone: CRYPTO_DISPLAY_TIME_ZONE,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatLiveDateTime(value: string | null | undefined, locale: string) {
  const date = parseCryptoUtcDateTime(value);
  if (!date) return "-";

  return date.toLocaleString(locale, {
    timeZone: CRYPTO_DISPLAY_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function cryptoTaipeiDateTimeParts(value: string | null | undefined) {
  const date = parseCryptoUtcDateTime(value);
  if (!date) return null;

  const parts = CRYPTO_TAIPEI_CHART_TIME_FORMATTER.formatToParts(date);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const { year, month, day, hour, minute, second } = byType;
  if (!year || !month || !day || !hour || !minute || !second) return null;

  return {
    year,
    month,
    day,
    hour,
    minute,
    second,
  };
}

function toCryptoTaipeiChartTime(value: string) {
  const parts = cryptoTaipeiDateTimeParts(value);
  if (!parts) return value;

  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}

function toCryptoTaipeiChartPoint(point: ChartPoint): ChartPoint {
  return {
    ...point,
    time: toCryptoTaipeiChartTime(point.time),
  };
}

function compactProviderLabel(provider: string) {
  if (provider === "bitopro") return "BitoPro";
  if (provider === "binance") return "Binance";
  if (provider === "okx") return "OKX";
  return provider;
}

function barToChartPoint(bar: CryptoOhlcvBar): ChartPoint {
  return {
    time: bar.bar_time,
    open: bar.open_price,
    high: bar.high_price,
    low: bar.low_price,
    close: bar.close_price,
    volume: bar.base_volume,
    trade_value: bar.quote_volume,
    transaction_count: null,
  };
}

function realtimeNumber(data: Record<string, unknown>, key: string) {
  const value = data[key];
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function realtimeString(data: Record<string, unknown>, key: string) {
  const value = data[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function normalizeChartTimestamp(value: string | null | undefined) {
  if (!value) return null;

  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/
  );
  if (!match) return null;

  const [, year, month, day, hour, minute, second = "00"] = match;
  return `${year}-${month}-${day}T${hour}:${minute}:${second}`;
}

function chartTimestampMs(value: string | null | undefined) {
  const normalized = normalizeChartTimestamp(value);
  if (!normalized) return null;

  const match = normalized.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/
  );
  if (!match) return null;

  const [, year, month, day, hour, minute, second] = match;
  return Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second)
  );
}

function chartTimestampFromMs(value: number) {
  return new Date(value).toISOString().slice(0, 19);
}

function weeklyBucketTimestampMs(value: number) {
  const date = new Date(value);
  const day = date.getUTCDay();
  const daysSinceMonday = (day + 6) % 7;
  return Date.UTC(
    date.getUTCFullYear(),
    date.getUTCMonth(),
    date.getUTCDate() - daysSinceMonday,
    0,
    0,
    0
  );
}

function monthlyBucketTimestampMs(value: number) {
  const date = new Date(value);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1, 0, 0, 0);
}

function bucketChartTimestamp(value: string | null | undefined, interval: CryptoInterval) {
  const timestampMs = chartTimestampMs(value);
  if (timestampMs === null) return normalizeChartTimestamp(value);

  if (interval === "1w") return chartTimestampFromMs(weeklyBucketTimestampMs(timestampMs));
  if (interval === "1M") return chartTimestampFromMs(monthlyBucketTimestampMs(timestampMs));

  const intervalMs = LIVE_CHART_INTERVAL_MS_BY_INTERVAL[interval];
  if (!intervalMs) return normalizeChartTimestamp(value);

  return chartTimestampFromMs(Math.floor(timestampMs / intervalMs) * intervalMs);
}

function midpointPrice(data: Record<string, unknown>) {
  const bid = realtimeNumber(data, "best_bid_price") ?? realtimeNumber(data, "bid_price");
  const ask = realtimeNumber(data, "best_ask_price") ?? realtimeNumber(data, "ask_price");
  if (bid !== null && ask !== null) return (bid + ask) / 2;
  return bid ?? ask;
}

function liveCloseFromRealtimeRow(row: CryptoRealtimeLatest) {
  if (row.resource === "ohlcv") return realtimeNumber(row.data, "close_price");
  if (row.resource === "ticker") return realtimeNumber(row.data, "last_price");
  if (row.resource === "order_book") return midpointPrice(row.data);
  return null;
}

function realtimeRowReceivedAtMs(row: CryptoRealtimeLatest) {
  const receivedAt = new Date(row.received_at).getTime();
  if (!Number.isNaN(receivedAt)) return receivedAt;

  const eventTime = row.event_time ? new Date(row.event_time).getTime() : NaN;
  return Number.isNaN(eventTime) ? 0 : eventTime;
}

function latestPriceRealtimeRow(rows: CryptoRealtimeLatest[]) {
  return rows.reduce<CryptoRealtimeLatest | null>((latestRow, row) => {
    if (liveCloseFromRealtimeRow(row) === null) return latestRow;
    if (!latestRow) return row;

    return realtimeRowReceivedAtMs(row) > realtimeRowReceivedAtMs(latestRow) ? row : latestRow;
  }, null);
}

function liveChartUpdateFromRealtimeRows(
  rows: CryptoRealtimeLatest[],
  interval: CryptoInterval
): LiveChartUpdate | null {
  if (!LIVE_CHART_RENDER_INTERVALS.has(interval)) return null;

  const activeRows = rows.filter((row) => !row.stale);
  const candleRow =
    activeRows.find((row) => row.resource === "ohlcv" && liveCloseFromRealtimeRow(row) !== null) ??
    null;
  const priceRow = latestPriceRealtimeRow(activeRows);
  if (!priceRow) return null;

  const close = liveCloseFromRealtimeRow(priceRow);
  if (close === null) return null;

  const row = candleRow ?? priceRow;
  const rawTime =
    (candleRow ? realtimeString(candleRow.data, "bar_time") : null) ??
    row.event_time ??
    row.received_at;
  const time = bucketChartTimestamp(rawTime, interval);
  if (!time) return null;

  const open = candleRow ? realtimeNumber(candleRow.data, "open_price") : null;
  const high = candleRow ? realtimeNumber(candleRow.data, "high_price") : null;
  const low = candleRow ? realtimeNumber(candleRow.data, "low_price") : null;

  return {
    provider: row.provider,
    symbol: row.symbol,
    instrumentType: row.instrument_type,
    resource: row.resource,
    priceResource: priceRow.resource,
    interval,
    time,
    close,
    open,
    high,
    low,
    volume: candleRow ? realtimeNumber(candleRow.data, "base_volume") : null,
    tradeValue: candleRow ? realtimeNumber(candleRow.data, "quote_volume") : null,
    receivedAt: priceRow.received_at,
    sequence: priceRow.sequence,
    lastMessageAgeMs: priceRow.last_message_age_ms,
  };
}

function liveChartUpdateFromStreamPayload(
  payload: unknown,
  interval: CryptoInterval
): LiveChartUpdate | null {
  if (
    !payload ||
    typeof payload !== "object" ||
    !Array.isArray((payload as Partial<CryptoRealtimeStreamPayload>).rows)
  ) {
    return null;
  }

  return liveChartUpdateFromRealtimeRows(
    (payload as CryptoRealtimeStreamPayload).rows,
    interval
  );
}

function liveChartUpdateSignature(update: LiveChartUpdate | null) {
  if (!update) return "";
  return [
    update.provider,
    update.symbol,
    update.instrumentType,
    update.resource,
    update.priceResource,
    update.interval,
    update.time,
    update.close,
    update.receivedAt,
    update.sequence ?? "",
  ].join("|");
}

function compactRange(values: Array<number | null | undefined>) {
  return values.filter(
    (value): value is number => typeof value === "number" && Number.isFinite(value)
  );
}

function mergeLiveChartUpdate(
  chartData: ChartPoint[],
  update: LiveChartUpdate | null,
  interval: CryptoInterval,
  limit: number
) {
  if (!LIVE_CHART_RENDER_INTERVALS.has(interval) || !update || chartData.length === 0) {
    return chartData;
  }

  const updateTimeMs = chartTimestampMs(update.time);
  if (updateTimeMs === null) return chartData;

  const next = chartData.slice();
  const matchingIndex = next.findIndex((point) => chartTimestampMs(point.time) === updateTimeMs);

  if (matchingIndex >= 0) {
    const current = next[matchingIndex];
    const open = current.open ?? update.open ?? update.close;
    const highCandidates = compactRange([current.high, update.high, open, update.close]);
    const lowCandidates = compactRange([current.low, update.low, open, update.close]);

    next[matchingIndex] = {
      ...current,
      open,
      high: highCandidates.length ? Math.max(...highCandidates) : update.close,
      low: lowCandidates.length ? Math.min(...lowCandidates) : update.close,
      close: update.close,
      volume: interval === "1m" ? update.volume ?? current.volume : current.volume ?? update.volume,
      trade_value:
        interval === "1m"
          ? update.tradeValue ?? current.trade_value
          : current.trade_value ?? update.tradeValue,
    };
    return next;
  }

  const last = next[next.length - 1];
  const lastTimeMs = chartTimestampMs(last?.time);
  if (lastTimeMs !== null && updateTimeMs <= lastTimeMs) return chartData;

  const open = interval === "1m"
    ? update.open ?? last?.close ?? update.close
    : last?.close ?? update.open ?? update.close;
  const highCandidates = compactRange([update.high, open, update.close]);
  const lowCandidates = compactRange([update.low, open, update.close]);
  const livePoint: ChartPoint = {
    time: update.time,
    open,
    high: highCandidates.length ? Math.max(...highCandidates) : update.close,
    low: lowCandidates.length ? Math.min(...lowCandidates) : update.close,
    close: update.close,
    volume: update.volume,
    trade_value: update.tradeValue,
    transaction_count: null,
  };

  return [...next, livePoint].slice(-limit);
}

function statusClass(state: LoadState) {
  if (state === "success") return "border-omi-market-up/40 text-omi-market-up";
  if (state === "loading") return "border-omi-warning/40 text-omi-warning";
  if (state === "error") return "border-omi-danger/50 text-omi-danger";
  return "border-omi-border text-omi-text-muted";
}

function intervalSupported(provider: string, interval: CryptoInterval) {
  return Boolean(provider && interval);
}

function summaryTimeframeForInterval(interval: CryptoInterval): SummaryTimeframe | null {
  if (interval === "1m") return "today";
  if (interval === "1d") return "daily";
  if (interval === "1w") return "weekly";
  if (interval === "1M") return "monthly";
  return null;
}

function chartDrawingStorageKey(instrumentKey: string, interval: CryptoInterval) {
  return `omi:crypto:chart-drawings:v1:${instrumentKey}:${interval}`;
}

function chartTimeMode(interval: CryptoInterval) {
  return interval === "1d" || interval === "1w" || interval === "1M" ? "date" : "intraday";
}

function instrumentSourceProviders(instrument: CryptoKLineInstrument): CryptoProvider[] {
  return instrument.sourceProviders?.length ? instrument.sourceProviders : [instrument.provider];
}

function instrumentPrimaryProvider(instrument: CryptoKLineInstrument): CryptoProvider {
  return instrument.primaryProvider ?? instrument.provider;
}

function instrumentSupportsInterval(instrument: CryptoKLineInstrument, interval: CryptoInterval) {
  const providers = instrumentSourceProviders(instrument);
  return providers.every((provider) => intervalSupported(provider, interval));
}

function mergeProviderBars(
  rows: CryptoOhlcvBar[],
  providers: CryptoProvider[],
  primaryProvider: CryptoProvider,
  limit: number
) {
  if (providers.length <= 1) return rows.slice(0, limit);

  const providerRank = new Map(
    [primaryProvider, ...providers.filter((provider) => provider !== primaryProvider)].map(
      (provider, index) => [provider, index]
    )
  );
  const byBarTime = new Map<string, CryptoOhlcvBar>();

  rows.forEach((row) => {
    const current = byBarTime.get(row.bar_time);
    if (!current) {
      byBarTime.set(row.bar_time, row);
      return;
    }

    const currentRank = providerRank.get(current.provider as CryptoProvider) ?? providers.length;
    const rowRank = providerRank.get(row.provider as CryptoProvider) ?? providers.length;
    if (rowRank < currentRank) {
      byBarTime.set(row.bar_time, row);
      return;
    }

    if (rowRank === currentRank) {
      const currentFetchedAt = new Date(current.fetched_at).getTime();
      const rowFetchedAt = new Date(row.fetched_at).getTime();
      if (rowFetchedAt > currentFetchedAt) {
        byBarTime.set(row.bar_time, row);
      }
    }
  });

  return Array.from(byBarTime.values())
    .sort((left, right) => new Date(right.bar_time).getTime() - new Date(left.bar_time).getTime())
    .slice(0, limit);
}

function chartLimitForInterval(interval: CryptoInterval) {
  return CHART_LIMIT_BY_INTERVAL[interval] ?? 500;
}

function latestFetchedAtForBars(rows: CryptoOhlcvBar[]) {
  return rows.reduce<string | null>((latestValue, bar) => {
    if (!bar.fetched_at) return latestValue;
    if (!latestValue) return bar.fetched_at;
    return new Date(bar.fetched_at).getTime() > new Date(latestValue).getTime()
      ? bar.fetched_at
      : latestValue;
  }, null);
}

function autoRefreshReasonForBars(
  rows: CryptoOhlcvBar[],
  interval: CryptoInterval
): CryptoOhlcvRefreshReason | null {
  if (!rows.length) return "auto_empty";

  const latestFetchedAt = latestFetchedAtForBars(rows);
  if (!latestFetchedAt) return "auto_stale";

  const latestFetchedTime = new Date(latestFetchedAt).getTime();
  if (Number.isNaN(latestFetchedTime)) return "auto_stale";

  const staleMs = AUTO_REFRESH_STALE_MS_BY_INTERVAL[interval];
  return Date.now() - latestFetchedTime > staleMs ? "auto_stale" : null;
}

function autoRefreshReasonLabel(reason: CryptoOhlcvRefreshReason, t: TranslationFunction) {
  return t(`crypto.kline.refreshReasons.${reason}`);
}

function valueToneClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "text-omi-text-strong";
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text-strong";
}

type Props = {
  selectedBase: CryptoBaseAsset;
  selectedInstrumentKey: string | null;
  subscriptionSettings: MarketDataSubscriptionSettingsRead | null;
  klineInstruments?: CryptoKLineInstrument[];
  professionalMode?: boolean;
  onProfessionalModeChange?: (value: boolean) => void;
};

export default function CryptoKLinePanel({
  selectedBase,
  selectedInstrumentKey,
  subscriptionSettings,
  klineInstruments,
  professionalMode = false,
  onProfessionalModeChange,
}: Props) {
  const { locale, t } = useI18n();
  const [interval, setInterval] = useState<CryptoInterval>("1m");
  const [volumeMetric, setVolumeMetric] = useState<VolumeMetric>("base");
  const [chartIndicators, setChartIndicators] = useState<IndicatorSettings>(() => ({
    ...cryptoChartIndicators,
  }));
  const [activeIndicatorTemplate, setActiveIndicatorTemplate] =
    useState<IndicatorTemplateKey | null>(null);
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [professionalChartStyle, setProfessionalChartStyle] =
    useState<ProfessionalChartStyle>("candlestick");
  const [professionalIndicators, setProfessionalIndicators] = useState<IndicatorSettings>(() => ({
    ...cryptoChartIndicators,
  }));
  const [activeProfessionalIndicatorTemplate, setActiveProfessionalIndicatorTemplate] =
    useState<IndicatorTemplateKey | null>(null);
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
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [refreshing, setRefreshing] = useState(false);
  const [bars, setBars] = useState<CryptoOhlcvBar[]>([]);
  const [liveChartUpdate, setLiveChartUpdate] = useState<LiveChartUpdate | null>(null);
  const chartDrawingSyncTimerRef = useRef<number | null>(null);
  const autoRefreshAttemptsRef = useRef<Record<string, number>>({});
  const autoRefreshInFlightRef = useRef<string | null>(null);
  const instrumentUniverse = klineInstruments?.length ? klineInstruments : CRYPTO_KLINE_INSTRUMENTS;

  const availableInstruments = useMemo(
    () => cryptoInstrumentsForBase(selectedBase, instrumentUniverse),
    [instrumentUniverse, selectedBase]
  );
  const selectedInstrument =
    availableInstruments.find((instrument) => instrument.key === selectedInstrumentKey) ??
    availableInstruments.find((instrument) =>
      instrument.key === defaultCryptoInstrumentKeyForBase(selectedBase, instrumentUniverse)
    ) ??
    availableInstruments[0] ??
    instrumentUniverse[0] ??
    CRYPTO_KLINE_INSTRUMENTS[0];
  const selectedSourceProviders = useMemo(
    () => instrumentSourceProviders(selectedInstrument),
    [selectedInstrument]
  );
  const selectedPrimaryProvider = instrumentPrimaryProvider(selectedInstrument);

  const chartData = useMemo<ChartPoint[]>(() => {
    return [...bars]
      .sort((left, right) => new Date(left.bar_time).getTime() - new Date(right.bar_time).getTime())
      .map(barToChartPoint)
      .filter((point) => point.close !== null);
  }, [bars]);

  const effectiveInterval = instrumentSupportsInterval(selectedInstrument, interval) ? interval : "1d";
  const chartLimit = chartLimitForInterval(effectiveInterval);
  const activeLiveChartUpdate =
    liveChartUpdate?.provider === selectedPrimaryProvider &&
    liveChartUpdate.symbol === selectedInstrument.symbol &&
    liveChartUpdate.instrumentType === selectedInstrument.instrumentType &&
    liveChartUpdate.interval === effectiveInterval
      ? liveChartUpdate
      : null;
  const renderedChartData = useMemo(
    () => mergeLiveChartUpdate(chartData, activeLiveChartUpdate, effectiveInterval, chartLimit),
    [activeLiveChartUpdate, chartData, chartLimit, effectiveInterval]
  );
  const displayChartData = useMemo(
    () => renderedChartData.map(toCryptoTaipeiChartPoint),
    [renderedChartData]
  );
  const chartTitle = `${selectedInstrument.symbol} ${effectiveInterval}`;
  const chartSourceLabel = selectedInstrument.exchange;
  const chartStatusSource = `${chartSourceLabel} ${chartTitle}`;
  const chartIndicatorRevealKey = useMemo(
    () =>
      Object.entries(chartIndicators)
        .filter(([, enabled]) => enabled)
        .map(([key]) => key)
        .sort()
        .join(","),
    [chartIndicators]
  );
  const autoRefreshKey = `${selectedInstrument.key}:${effectiveInterval}`;
  const activeSummaryTimeframe = summaryTimeframeForInterval(effectiveInterval);
  const latestChartPoint = renderedChartData[renderedChartData.length - 1] ?? null;
  const previousChartPoint = renderedChartData[renderedChartData.length - 2] ?? null;
  const latestClose = latestChartPoint?.close ?? null;
  const previousClose = previousChartPoint?.close ?? null;
  const latestChange =
    latestClose !== null && previousClose !== null ? latestClose - previousClose : null;
  const latestChangePct =
    latestChange !== null && previousClose !== null && previousClose !== 0
      ? (latestChange / previousClose) * 100
      : null;
  const chartDrawingKey = chartDrawingStorageKey(selectedInstrument.key, effectiveInterval);
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
      market: "CRYPTO",
      symbol: selectedInstrument.key,
      timeframe: effectiveInterval,
    }),
    [effectiveInterval, selectedInstrument.key]
  );
  const ohlcvRefreshEnabled = cryptoSubscriptionResourceEnabled(
    subscriptionSettings,
    selectedInstrument.baseAsset,
    "ohlcv"
  );
  const latestFetchedAt = latestFetchedAtForBars(bars);
  const liveStatusLabel = LIVE_CHART_RENDER_INTERVALS.has(effectiveInterval)
    ? activeLiveChartUpdate
      ? t("crypto.kline.liveUpdate", {
          provider: compactProviderLabel(activeLiveChartUpdate.provider),
          time: formatLiveDateTime(activeLiveChartUpdate.receivedAt, locale),
        })
      : t("crypto.kline.liveWaiting")
    : null;

  const fetchBars = useCallback(async () => {
    const providerRows = await Promise.all(
      selectedSourceProviders.map((provider) =>
        fetchJson<CryptoOhlcvBar[]>("/api/crypto-market/ohlcv/latest", {
          provider,
          symbols: selectedInstrument.symbol,
          instrument_type: selectedInstrument.instrumentType,
          interval: effectiveInterval,
          limit: chartLimit,
        })
      )
    );

    return mergeProviderBars(
      providerRows.flat(),
      selectedSourceProviders,
      selectedPrimaryProvider,
      chartLimit
    );
  }, [
    chartLimit,
    effectiveInterval,
    selectedInstrument.instrumentType,
    selectedInstrument.symbol,
    selectedPrimaryProvider,
    selectedSourceProviders,
  ]);

  const liveRealtimeParams = useMemo(
    () => ({
      provider: selectedPrimaryProvider,
      symbol: selectedInstrument.symbol,
      instrument_type: selectedInstrument.instrumentType,
      interval_ms: LIVE_CHART_RENDER_INTERVAL_MS,
    }),
    [
      selectedInstrument.instrumentType,
      selectedInstrument.symbol,
      selectedPrimaryProvider,
    ]
  );

  const fetchLiveChartUpdate = useCallback(async (signal?: AbortSignal) => {
    if (!LIVE_CHART_RENDER_INTERVALS.has(effectiveInterval)) return null;

    const response = await fetch(buildApiUrl("/api/crypto-market/realtime/latest", {
      provider: liveRealtimeParams.provider,
      symbol: liveRealtimeParams.symbol,
      instrument_type: liveRealtimeParams.instrument_type,
    }), {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });

    if (!response.ok) {
      throw new Error(`API ${response.status}: ${response.statusText || "Request failed"}`);
    }

    const rows = await response.json() as CryptoRealtimeLatest[];
    return liveChartUpdateFromRealtimeRows(rows, effectiveInterval);
  }, [
    effectiveInterval,
    liveRealtimeParams,
  ]);

  const refreshBars = useCallback(async (
    reason: CryptoOhlcvRefreshReason = "manual",
    options?: { reloadAfter?: boolean; updateRefreshing?: boolean }
  ) => {
    if (!ohlcvRefreshEnabled) {
      if (reason === "manual") {
        emitDataStatusEvent({
          market: "crypto",
          level: "warning",
          title: t("crypto.kline.status.refreshDisabled"),
          message: t("crypto.kline.status.refreshDisabledMessage", {
            asset: selectedInstrument.baseAsset,
          }),
          source: chartStatusSource,
        });
      }
      return null;
    }

    const updateRefreshing = options?.updateRefreshing !== false;
    if (updateRefreshing) {
      setRefreshing(true);
    }

    try {
      const result = await requestJson<{
        status: string;
        refreshed_count: number;
        skipped_count: number;
        error_count: number;
      }>(
        "/api/crypto-market/ohlcv/refresh",
        { method: "POST" },
        {
          providers: selectedSourceProviders.join(","),
          symbols: selectedInstrument.symbol,
          interval: effectiveInterval,
          limit: Math.min(chartLimit, OHLCV_REFRESH_LIMIT_MAX),
        }
      );
      const shouldShowSuccess = reason === "manual" || reason === "auto_empty";
      if (result.error_count > 0 || shouldShowSuccess) {
        const reasonLabel = autoRefreshReasonLabel(reason, t);
        emitDataStatusEvent({
          market: "crypto",
          level: result.error_count > 0 ? "warning" : "success",
          title: result.error_count > 0
            ? t("crypto.kline.status.refreshPartial", { reason: reasonLabel })
            : t("crypto.kline.status.refreshComplete", { reason: reasonLabel }),
          message: t("crypto.kline.status.refreshResult", {
            status: result.status,
            refreshed: result.refreshed_count,
            skipped: result.skipped_count,
            errors: result.error_count,
          }),
          source: chartStatusSource,
        });
      }

      if (options?.reloadAfter !== false) {
        const rows = await fetchBars();
        setBars(rows);
        setLoadState("success");
      }
      return result;
    } catch (error) {
      const reasonLabel = autoRefreshReasonLabel(reason, t);
      emitDataStatusEvent({
        market: "crypto",
        level: "error",
        title: t("crypto.kline.status.refreshFailed", { reason: reasonLabel }),
        message: error instanceof Error ? error.message : "Failed to refresh crypto chart",
        source: chartStatusSource,
      });
      return null;
    } finally {
      if (updateRefreshing) {
        setRefreshing(false);
      }
    }
  }, [
    chartStatusSource,
    chartLimit,
    effectiveInterval,
    fetchBars,
    ohlcvRefreshEnabled,
    selectedInstrument.baseAsset,
    selectedInstrument.symbol,
    selectedSourceProviders,
    t,
  ]);

  const loadBars = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setLoadState("loading");
    }

    try {
      const rows = await fetchBars();
      setBars(rows);
      setLoadState("success");

      const staleRefreshReason = autoRefreshReasonForBars(rows, effectiveInterval);
      const autoRefreshReason =
        staleRefreshReason ??
        (LIVE_OHLCV_REFRESH_INTERVALS.has(effectiveInterval) ? "auto_poll" : null);
      if (!autoRefreshReason || !ohlcvRefreshEnabled) return;

      const now = Date.now();
      const throttleMs =
        autoRefreshReason === "auto_empty"
          ? AUTO_REFRESH_RETRY_BACKOFF_MS
          : autoRefreshReason === "auto_poll"
            ? LIVE_OHLCV_REFRESH_MIN_INTERVAL_MS
            : Math.max(AUTO_REFRESH_RETRY_BACKOFF_MS, AUTO_REFRESH_STALE_MS_BY_INTERVAL[effectiveInterval]);
      const lockKey = `${autoRefreshKey}:${autoRefreshReason}`;
      const lastAttemptAt = autoRefreshAttemptsRef.current[lockKey] ?? 0;
      if (autoRefreshInFlightRef.current || now - lastAttemptAt < throttleMs) return;

      autoRefreshAttemptsRef.current[lockKey] = now;
      autoRefreshInFlightRef.current = lockKey;
      try {
        const result = await refreshBars(autoRefreshReason, {
          reloadAfter: false,
          updateRefreshing: autoRefreshReason !== "auto_poll",
        });
        if (result !== null) {
          const refreshedRows = await fetchBars();
          setBars(refreshedRows);
          setLoadState("success");
        }
      } finally {
        if (autoRefreshInFlightRef.current === lockKey) {
          autoRefreshInFlightRef.current = null;
        }
      }
    } catch (error) {
      if (!silent) {
        emitDataStatusEvent({
          market: "crypto",
          level: "error",
          title: t("crypto.kline.status.loadFailed"),
          message: error instanceof Error ? error.message : "Failed to load crypto chart",
          source: chartStatusSource,
        });
        setLoadState("error");
      }
    }
  }, [
    autoRefreshKey,
    effectiveInterval,
    fetchBars,
    ohlcvRefreshEnabled,
    refreshBars,
    chartStatusSource,
    t,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadBars();
    }, 0);

    return () => window.clearTimeout(timer);
  }, [loadBars]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadBars({ silent: true });
    }, 10000);

    return () => window.clearInterval(timer);
  }, [loadBars]);

  useEffect(() => {
    if (!LIVE_CHART_RENDER_INTERVALS.has(effectiveInterval)) {
      return;
    }

    let cancelled = false;
    let fallbackTimer: number | null = null;
    let fallbackAbortController: AbortController | null = null;
    let eventSource: EventSource | null = null;
    let streamWatchdogTimer: number | null = null;
    let lastStreamSnapshotAt = 0;

    function applyLiveChartUpdate(nextUpdate: LiveChartUpdate | null) {
      if (cancelled) return;

      const nextSignature = liveChartUpdateSignature(nextUpdate);
      setLiveChartUpdate((current) =>
        liveChartUpdateSignature(current) === nextSignature ? current : nextUpdate
      );
    }

    function clearFallbackTimer() {
      if (fallbackTimer === null) return;
      window.clearTimeout(fallbackTimer);
      fallbackTimer = null;
    }

    function clearStreamWatchdog() {
      if (streamWatchdogTimer === null) return;
      window.clearTimeout(streamWatchdogTimer);
      streamWatchdogTimer = null;
    }

    function scheduleStreamWatchdog(delayMs = LIVE_CHART_STREAM_WATCHDOG_MS) {
      clearStreamWatchdog();
      streamWatchdogTimer = window.setTimeout(() => {
        if (cancelled || !eventSource) return;

        if (document.visibilityState !== "visible") {
          scheduleStreamWatchdog();
          return;
        }

        const snapshotAge = lastStreamSnapshotAt
          ? Date.now() - lastStreamSnapshotAt
          : Number.POSITIVE_INFINITY;
        if (snapshotAge >= LIVE_CHART_STREAM_WATCHDOG_MS) {
          startFallbackPolling();
          return;
        }

        scheduleStreamWatchdog(Math.max(250, LIVE_CHART_STREAM_WATCHDOG_MS - snapshotAge));
      }, delayMs);
    }

    function scheduleFallbackPoll(delayMs = LIVE_CHART_RENDER_INTERVAL_MS) {
      clearFallbackTimer();
      fallbackTimer = window.setTimeout(() => {
        void pollLiveChartUpdate();
      }, delayMs);
    }

    async function pollLiveChartUpdate() {
      if (cancelled) return;
      if (document.visibilityState !== "visible") return;

      fallbackAbortController?.abort();
      const abortController = new AbortController();
      fallbackAbortController = abortController;

      try {
        applyLiveChartUpdate(await fetchLiveChartUpdate(abortController.signal));
      } catch {
        if (!abortController.signal.aborted) {
          applyLiveChartUpdate(null);
        }
      } finally {
        if (fallbackAbortController === abortController) {
          fallbackAbortController = null;
        }
        if (!cancelled) {
          scheduleFallbackPoll();
        }
      }
    }

    function startFallbackPolling() {
      eventSource?.close();
      eventSource = null;
      clearStreamWatchdog();
      clearFallbackTimer();
      scheduleFallbackPoll(0);
    }

    if (typeof EventSource !== "undefined") {
      const source = new EventSource(
        buildApiUrl("/api/crypto-market/realtime/stream", liveRealtimeParams)
      );
      eventSource = source;

      source.addEventListener("snapshot", (event) => {
        if (cancelled) return;

        lastStreamSnapshotAt = Date.now();
        scheduleStreamWatchdog();

        try {
          applyLiveChartUpdate(
            liveChartUpdateFromStreamPayload(JSON.parse(event.data), effectiveInterval)
          );
        } catch {
          applyLiveChartUpdate(null);
        }
      });
      source.onerror = () => {
        if (cancelled) return;
        startFallbackPolling();
      };
      scheduleStreamWatchdog();
    } else {
      startFallbackPolling();
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible") {
        fallbackAbortController?.abort();
        clearFallbackTimer();
        clearStreamWatchdog();
        return;
      }

      if (!eventSource) {
        scheduleFallbackPoll(0);
      } else {
        scheduleStreamWatchdog(0);
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      eventSource?.close();
      clearStreamWatchdog();
      clearFallbackTimer();
      fallbackAbortController?.abort();
    };
  }, [effectiveInterval, fetchLiveChartUpdate, liveRealtimeParams]);

  const volumePanelLabel =
    volumeMetric === "base"
      ? t("crypto.kline.baseVolumeWithAsset", { asset: selectedInstrument.baseAsset })
      : t("crypto.kline.quoteVolumeWithAsset", { asset: selectedInstrument.quoteAsset });
  const chartMinHeight = professionalMode ? "min-h-[620px]" : "min-h-[420px]";
  const emptyHeight = professionalMode ? "h-[620px]" : "h-[420px]";

  const queueChartDrawingRemoteSave = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave: string | null
  ) => {
    if (typeof window === "undefined") return;

    const path = chartDrawingApiPath("CRYPTO", selectedInstrument.key, effectiveInterval);
    const payload = buildChartDrawingSnapshotPayload({
      drawings: drawingsToSave,
      market: "CRYPTO",
      selectedDrawingId: selectedDrawingIdToSave,
      source: "frontend.crypto_professional_chart",
      stockName: chartTitle,
      symbol: selectedInstrument.key,
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
        // Best-effort server sync. Local chart drawings remain available via localStorage.
      });
    }, chartDrawingSyncDelayMs);
  }, [chartTitle, effectiveInterval, selectedInstrument.key]);

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
    if (!professionalMode) return;

    let cancelled = false;
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
          chartDrawingApiPath("CRYPTO", selectedInstrument.key, effectiveInterval)
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
        // A missing remote snapshot simply means this crypto chart has not been saved server-side yet.
      }
    }

    void loadRemoteChartDrawings();

    return () => {
      cancelled = true;
    };
  }, [
    activeSelectedChartDrawingId,
    chartDrawingKey,
    effectiveInterval,
    professionalMode,
    queueChartDrawingRemoteSave,
    selectedInstrument.key,
  ]);

  function applyProfessionalIndicatorTemplate(templateKey: IndicatorTemplateKey) {
    const template = indicatorTemplates.find((item) => item.key === templateKey);
    if (!template) return;

    setProfessionalIndicators({ ...template.indicators });
    setActiveProfessionalIndicatorTemplate(templateKey);
  }

  function toggleProfessionalIndicator(key: IndicatorKey) {
    setProfessionalIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
    setActiveProfessionalIndicatorTemplate(null);
  }

  function applyIndicatorTemplate(templateKey: IndicatorTemplateKey) {
    const template = indicatorTemplates.find((item) => item.key === templateKey);
    if (!template) return;

    setChartIndicators({ ...template.indicators });
    setActiveIndicatorTemplate(templateKey);
  }

  function toggleChartIndicator(key: IndicatorKey) {
    setChartIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
    setActiveIndicatorTemplate(null);
  }

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
    if (!window.confirm("清除這個 Crypto 圖表的所有畫線？")) return;

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

  if (professionalMode) {
    return (
      <ProfessionalChartPanel
        title={chartTitle}
        priceSummary={
          <div className={["flex items-baseline gap-2", valueToneClass(latestChange)].join(" ")}>
            <PriceUpdatePulse
              value={latestClose}
              direction={latestChange}
              resetKey={`${selectedInstrument.key}:crypto-professional:${effectiveInterval}`}
              className="text-2xl font-bold leading-none tracking-normal tabular-nums"
            >
              {formatCryptoPrice(latestClose)}
            </PriceUpdatePulse>
            <span className="text-sm font-semibold tabular-nums">
              {formatSignedNumber(latestChange)}
            </span>
            <span className="text-sm font-semibold tabular-nums">
              ({formatPct(latestChangePct)})
            </span>
          </div>
        }
        timeframeOptions={PROFESSIONAL_INTERVAL_OPTIONS.filter((option) =>
          instrumentSupportsInterval(selectedInstrument, option.interval)
        ).map((option) => ({
          key: option.interval,
          label: t(`crypto.intervals.${option.interval}`),
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
            indicators={professionalIndicators}
            activeTemplate={activeProfessionalIndicatorTemplate}
            onApplyTemplate={applyProfessionalIndicatorTemplate}
            onToggleIndicator={toggleProfessionalIndicator}
            groups={professionalIndicatorCategoryGroups}
            className="w-[28rem]"
          />
        }
        onClose={() => {
          setIndicatorMenuOpen(false);
          setChartDrawingTool("cursor");
          onProfessionalModeChange?.(false);
        }}
        drawingToolbarStart={
          <>
            <button
              type="button"
              className={[
                "h-7 px-2 text-xs font-semibold transition",
                volumeMetric === "base"
                  ? "bg-omi-control text-omi-text-inverse"
                  : "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong",
              ].join(" ")}
              onClick={() => setVolumeMetric("base")}
            >
              {t("crypto.kline.baseVolume")}
            </button>
            <button
              type="button"
              className={[
                "h-7 px-2 text-xs font-semibold transition",
                volumeMetric === "quote"
                  ? "bg-omi-control text-omi-text-inverse"
                  : "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong",
              ].join(" ")}
              onClick={() => setVolumeMetric("quote")}
            >
              {t("crypto.kline.quoteVolume")}
            </button>
            <button
              type="button"
              className="h-7 px-2 text-xs font-semibold text-omi-text-muted transition hover:bg-omi-surface hover:text-omi-text-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
              onClick={() => void loadBars()}
              disabled={loadState === "loading" || refreshing}
            >
              {t("crypto.kline.reload")}
            </button>
            <button
              type="button"
              className="h-7 px-2 text-xs font-semibold text-omi-accent transition hover:bg-omi-surface hover:text-omi-text-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
              onClick={() => void refreshBars()}
              disabled={refreshing || !ohlcvRefreshEnabled}
            >
              {refreshing ? t("crypto.kline.refreshing") : t("crypto.kline.refreshOhlcv")}
            </button>
          </>
        }
        chartReady={displayChartData.length > 0}
        emptyState={
          <div className="flex h-[640px] items-center justify-center border-t border-omi-border-subtle px-4 text-center text-sm text-omi-text-muted">
            {loadState === "loading" || refreshing
              ? t("crypto.kline.loadingBars")
              : t("crypto.kline.emptyBars")}
          </div>
        }
        chartData={displayChartData}
        label={chartTitle}
        timeMode={chartTimeMode(effectiveInterval)}
        showMovingAverages={professionalIndicators.ma}
        indicators={professionalIndicators}
        indicatorParameters={defaultIndicatorParameters}
        volumePanelLabel={volumePanelLabel}
        volumeValueKey={volumeMetric === "base" ? "volume" : "trade_value"}
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
    <section className="border border-omi-border-subtle bg-omi-surface">
      <header className="border-b border-omi-border-subtle px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              {t("crypto.kline.sectionTitle")}
            </div>
            <h2 className="mt-1 text-xl font-bold text-omi-text-strong">{chartTitle}</h2>
            <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs text-omi-text-muted">
              <span>{chartSourceLabel}</span>
              <span>/</span>
              <span>
                {t("crypto.kline.latestFetch", {
                  time: formatDateTime(latestFetchedAt, locale),
                })}
              </span>
              <span>/</span>
              <span>{t("crypto.kline.bars", { count: displayChartData.length })}</span>
              {liveStatusLabel ? (
                <>
                  <span>/</span>
                  <span className="text-omi-accent">{liveStatusLabel}</span>
                </>
              ) : null}
            </div>
          </div>
          <div className="ml-auto flex min-w-[260px] flex-col items-end gap-2">
            {!professionalMode ? (
              <div className="inline-flex border border-omi-border-subtle bg-omi-surface-subtle">
                {SUMMARY_TIMEFRAME_OPTIONS.map((option) => {
                  const disabled = !instrumentSupportsInterval(selectedInstrument, option.interval);

                  return (
                    <button
                      key={option.key}
                      type="button"
                      className={`h-8 min-w-12 border-r border-omi-border-subtle px-3 text-sm font-semibold transition last:border-r-0 disabled:cursor-not-allowed disabled:opacity-40 ${
                        activeSummaryTimeframe === option.key
                          ? "border-omi-accent bg-omi-accent-soft text-omi-accent shadow-[inset_0_-2px_0_theme(colors.omi.accent)]"
                          : "text-omi-text-muted hover:bg-omi-surface-muted hover:text-omi-text"
                      }`}
                      onClick={() => {
                        setIndicatorMenuOpen(false);
                        setInterval(option.interval);
                      }}
                      disabled={disabled}
                      title={disabled ? t("crypto.kline.intervalUnavailable") : undefined}
                    >
                      {t(`crypto.summaryTimeframes.${option.key}`)}
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="flex flex-wrap justify-end gap-1">
                {PROFESSIONAL_INTERVAL_OPTIONS.map((option) => {
                  const disabled = !instrumentSupportsInterval(selectedInstrument, option.interval);

                  return (
                    <button
                      key={option.interval}
                      type="button"
                      className={`h-8 min-w-10 border px-3 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
                        option.interval === effectiveInterval
                          ? "border-omi-accent bg-omi-accent-soft text-omi-accent"
                          : "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-muted hover:border-omi-border"
                      }`}
                      onClick={() => {
                        setIndicatorMenuOpen(false);
                        setInterval(option.interval);
                      }}
                      disabled={disabled}
                      title={disabled ? t("crypto.kline.intervalUnavailable") : undefined}
                    >
                      {t(`crypto.intervals.${option.interval}`)}
                    </button>
                  );
                })}
              </div>
            )}

            <div className="flex flex-wrap justify-end gap-2">
              {professionalMode ? (
                <>
                  <span className={`border px-2 py-1 text-xs font-semibold ${statusClass(loadState)}`}>
                    {loadState}
                  </span>
                  <button
                    type="button"
                    className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted transition hover:border-omi-accent hover:text-omi-accent disabled:cursor-not-allowed disabled:opacity-60"
                    onClick={() => void loadBars()}
                    disabled={loadState === "loading" || refreshing}
                  >
                    {t("crypto.kline.reload")}
                  </button>
                  <button
                    type="button"
                    className="h-8 border border-omi-accent-border bg-omi-accent-soft px-3 text-xs font-semibold text-omi-accent transition hover:border-omi-accent hover:bg-omi-surface-subtle disabled:cursor-not-allowed disabled:opacity-60"
                    onClick={() => void refreshBars()}
                    disabled={refreshing || !ohlcvRefreshEnabled}
                  >
                    {refreshing ? t("crypto.kline.refreshing") : t("crypto.kline.refreshOhlcv")}
                  </button>
                </>
              ) : null}
              <div className="relative">
                <button
                  type="button"
                  className={`h-8 border px-3 text-sm font-semibold transition ${
                    indicatorMenuOpen
                      ? "border-omi-accent bg-omi-accent-soft text-omi-accent"
                      : "border-omi-border bg-omi-surface text-omi-text-muted hover:border-omi-accent hover:text-omi-accent"
                  }`}
                  onClick={() => setIndicatorMenuOpen((value) => !value)}
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
                className={`h-8 border px-3 text-sm font-semibold transition ${
                  professionalMode
                    ? "border-omi-accent bg-omi-accent-soft text-omi-accent"
                    : "border-omi-border bg-omi-surface text-omi-text-muted hover:border-omi-accent hover:text-omi-accent"
                }`}
                onClick={() => {
                  setIndicatorMenuOpen(false);
                  onProfessionalModeChange?.(!professionalMode);
                }}
              >
                {professionalMode ? t("crypto.kline.overview") : t("crypto.kline.expand")}
              </button>
            </div>
          </div>
        </div>

        {professionalMode ? (
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              className={`h-8 border px-3 text-xs font-semibold transition ${
                volumeMetric === "base"
                  ? "border-omi-accent bg-omi-accent-soft text-omi-accent"
                  : "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-muted hover:border-omi-border"
              }`}
              onClick={() => setVolumeMetric("base")}
            >
              {t("crypto.kline.baseVolume")}
            </button>
            <button
              type="button"
              className={`h-8 border px-3 text-xs font-semibold transition ${
                volumeMetric === "quote"
                  ? "border-omi-accent bg-omi-accent-soft text-omi-accent"
                  : "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-muted hover:border-omi-border"
              }`}
              onClick={() => setVolumeMetric("quote")}
            >
              {t("crypto.kline.quoteVolume")}
            </button>
          </div>
        ) : null}
      </header>

      <div className={`${chartMinHeight} px-3 py-3`}>
        {displayChartData.length > 0 ? (
          <StockKLineChart
            chartData={displayChartData}
            label={chartTitle}
            indicators={chartIndicators}
            indicatorParameters={defaultIndicatorParameters}
            revealKey={`crypto-${selectedInstrument.key}-${effectiveInterval}-${displayChartData.length}-${chartIndicatorRevealKey}`}
            volumePanelLabel={volumePanelLabel}
            volumeTooltipLabel={volumePanelLabel}
            volumeValueKey={volumeMetric === "base" ? "volume" : "trade_value"}
            volumeValueFormatter={formatCryptoVolume}
          />
        ) : (
          <div className={`flex ${emptyHeight} items-center justify-center border border-dashed border-omi-border-subtle bg-omi-surface-subtle px-4 text-center text-sm text-omi-text-muted`}>
            {loadState === "loading" || refreshing
              ? t("crypto.kline.loadingBars")
              : t("crypto.kline.emptyBars")}
          </div>
        )}
      </div>
    </section>
  );
}

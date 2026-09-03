"use client";

import type { IntradayInterval } from "@/components/IntradayTrendChart";
import {
  formatDateTime,
  isProfessionalIntradayTimeframe,
  type ChartTimeframe,
  type LoadState,
  type ProfessionalIntradayTimeframe,
  type ProfessionalTimeframe,
  type Timeframe,
} from "@/components/stock-detail/StockDetailDataViews";
import { fetchJson } from "@/lib/api";
import type { DataStatusLevel } from "@/lib/dataStatusEvents";
import { getMarketCalendarStatusSnapshot } from "@/lib/marketCalendarStatus";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  getTaiwanMarketRefreshState,
} from "@/lib/taiwanMarketTime";
import { timeframeLabel, type TranslationFunction } from "@/i18n";
import type {
  ChartPoint,
  IntradayCurrentObservation,
  IntradayPriceDiagnostics,
  IntradayTrendCapabilities,
  IntradayTrendPoint,
  OhlcIntradayOverlay,
  StockIndicatorPoint,
  TaiwanBarSeriesRead,
  TaiwanChartBarSeriesRead,
  TaiwanCanonicalBarPoint,
  TaiwanTechnicalCapabilityContract,
  TaiwanTechnicalSeriesRead,
} from "@/types/market";
import { useEffect, useRef, useState } from "react";

const chartBarsByTimeframe: Record<ChartTimeframe, number> = {
  daily: 260,
  weekly: 520,
  monthly: 132,
};
const INDEX_DAILY_CHART_BARS = 300;
const emptyChartPoints: ChartPoint[] = [];
const emptyIndicatorPoints: StockIndicatorPoint[] = [];
const emptyIntradayTrendPoints: IntradayTrendPoint[] = [];
const TAIWAN_CHART_REFRESH_LIMIT = 8;
const TAIWAN_CHART_REFRESH_MIN_MS = 15_000;
const TAIWAN_CHART_REFRESH_MAX_MS = 60_000;
const TODAY_PRESENTATION_CACHE_MAX_SYMBOLS = 10;
const TODAY_PRESENTATION_CACHE_TTL_MS = 15 * 60 * 1000;
const TODAY_WARMING_RETRY_DELAYS_MS = [1_000, 2_000, 3_000, 5_000] as const;
const missingIntradayCapabilities: IntradayTrendCapabilities = {
  supports_volume: false,
  supports_vwap: false,
  supports_price_limit: true,
  supports_quote_depth: true,
};

type PublishDataStatus = (status: {
  level?: DataStatusLevel;
  message: string;
  source?: string;
  statusKey?: string;
  title: string;
}) => void;

type UseTaiwanStockChartDataOptions = {
  chartFocusMode: boolean;
  currentStockInfoMarket: string | null;
  effectiveTimeframe: Timeframe;
  isIndexProduct: boolean;
  professionalTimeframe: ProfessionalTimeframe;
  publishDataStatus: PublishDataStatus;
  reloadNonce: number;
  stockId: string | null;
  t: TranslationFunction;
  todayInterval: IntradayInterval;
};

type DailyChartState = {
  chartData: ChartPoint[];
  indicatorData: StockIndicatorPoint[];
  intradayOverlay: OhlcIntradayOverlay | null;
  stockId: string;
  timeframe: ChartTimeframe;
  volumeUnit: string | null;
};

export type TodaySnapshotPhase = "warming" | "ready" | "degraded";

type TodaySnapshotMetadata = {
  phase: TodaySnapshotPhase;
  revision: string | null;
  barCount: number | null;
  availableFrom: string | null;
  availableTo: string | null;
  reasonCodes: string[];
};

type TodayChartState = {
  capabilities: IntradayTrendCapabilities;
  currentObservation: IntradayCurrentObservation | null;
  previousClose: number | null;
  priceDiagnostics: IntradayPriceDiagnostics | null;
  source: string;
  stockId: string;
  tradeDate: string | null;
  trend: IntradayTrendPoint[];
  updatedAt: string | null;
  historyStatus: string;
  interval: string;
  snapshotPhase: TodaySnapshotPhase;
  snapshotRevision: string | null;
  snapshotBarCount: number | null;
  snapshotAvailableFrom: string | null;
  snapshotAvailableTo: string | null;
  snapshotReasonCodes: string[];
};

type TodayPresentationCacheEntry = {
  cachedAt: number;
  state: TodayChartState;
};

function todayPresentationCacheKey(state: TodayChartState) {
  return `${state.stockId}:${state.tradeDate ?? "unknown"}:${state.interval}`;
}

function rememberTodayPresentation(
  cache: Map<string, TodayPresentationCacheEntry>,
  state: TodayChartState,
  cachedAt = Date.now()
) {
  if (!isTodayPresentationCacheEligible(state)) return;
  const key = todayPresentationCacheKey(state);
  cache.delete(key);
  cache.set(key, { cachedAt, state });
  while (cache.size > TODAY_PRESENTATION_CACHE_MAX_SYMBOLS) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) break;
    cache.delete(oldestKey);
  }
}

export function snapshotPhaseForCoverage(
  status: NonNullable<TaiwanBarSeriesRead["current_session_coverage"]>["status"] | undefined
): TodaySnapshotPhase {
  if (status === "complete_prefix" || status === "complete_session") return "ready";
  // Older rolling runtimes did not publish the Backend-owned phase. Fail
  // closed for partial coverage instead of recreating the Ready Gate here.
  return "warming";
}

export function isTodayPresentationCacheEligible(
  state: Pick<TodayChartState, "snapshotPhase" | "tradeDate" | "trend">
) {
  return Boolean(
    state.tradeDate && state.snapshotPhase !== "warming" && state.trend.length >= 2
  );
}

function todaySnapshotMetadata(
  series: TaiwanRenderableBarSeries,
  {
    fullSnapshot,
    returnedBarCount,
  }: { fullSnapshot: boolean; returnedBarCount: number }
): TodaySnapshotMetadata {
  const coverage = series.current_session_coverage;
  const phase = coverage?.snapshot_phase ?? snapshotPhaseForCoverage(coverage?.status);
  const first = series.bars[0] ?? null;
  const last = series.bars[series.bars.length - 1] ?? null;
  return {
    phase,
    revision: coverage?.snapshot_revision ?? null,
    barCount:
      coverage?.snapshot_bar_count ?? (fullSnapshot ? returnedBarCount : null),
    availableFrom:
      coverage?.snapshot_available_from ?? (fullSnapshot ? first?.start_at ?? null : null),
    availableTo:
      coverage?.snapshot_available_to ?? (fullSnapshot ? last?.end_at ?? null : null),
    reasonCodes:
      coverage?.snapshot_reason_codes ?? [
        coverage ? `TW_CHART_SNAPSHOT_${coverage.status.toUpperCase()}` : "TW_CHART_SNAPSHOT_METADATA_MISSING",
      ],
  };
}

export function shouldRecoverTodayFullSnapshot({
  fullSnapshot,
  mergedPointCount,
  returnedPointCount,
  next,
  previous,
}: {
  fullSnapshot: boolean;
  mergedPointCount: number;
  returnedPointCount: number;
  next: TodaySnapshotMetadata;
  previous: Pick<
    TodayChartState,
    "snapshotAvailableFrom" | "snapshotPhase" | "snapshotRevision"
  > | null;
}) {
  if (fullSnapshot || next.phase === "warming") return false;
  if (!previous || previous.snapshotPhase === "warming") return true;
  if (next.barCount !== null && mergedPointCount < next.barCount) return true;
  if (
    next.revision &&
    previous.snapshotRevision &&
    next.revision !== previous.snapshotRevision &&
    (next.barCount === null || returnedPointCount < next.barCount)
  ) {
    return true;
  }
  return Boolean(
    next.revision &&
      previous.snapshotRevision &&
      next.revision !== previous.snapshotRevision &&
      next.availableFrom &&
      previous.snapshotAvailableFrom &&
      next.availableFrom < previous.snapshotAvailableFrom
  );
}

function readTodayPresentation(
  cache: Map<string, TodayPresentationCacheEntry>,
  stockId: string,
  interval: string,
  expectedTradeDate: string | null,
  now = Date.now()
) {
  let selectedKey: string | null = null;
  let selected: TodayPresentationCacheEntry | null = null;
  for (const [key, entry] of cache) {
    if (now - entry.cachedAt > TODAY_PRESENTATION_CACHE_TTL_MS) {
      cache.delete(key);
      continue;
    }
    if (
      entry.state.stockId === stockId &&
      entry.state.interval === interval &&
      (expectedTradeDate === null || entry.state.tradeDate !== expectedTradeDate)
    ) {
      cache.delete(key);
      continue;
    }
    if (
      entry.state.stockId === stockId &&
      entry.state.interval === interval &&
      entry.state.tradeDate === expectedTradeDate &&
      (!selected || entry.cachedAt > selected.cachedAt)
    ) {
      selectedKey = key;
      selected = entry;
    }
  }
  if (!selected || !selectedKey) return null;
  cache.delete(selectedKey);
  cache.set(selectedKey, selected);
  return selected.state;
}

type ScopedLoadState = {
  requestKey: string;
  state: LoadState;
};

const intervalByChartTimeframe: Record<ChartTimeframe, "1d" | "1w" | "1mo"> = {
  daily: "1d",
  weekly: "1w",
  monthly: "1mo",
};

function numberOrNull(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

type TaiwanRenderableBarSeries = TaiwanBarSeriesRead | TaiwanChartBarSeriesRead;

function chartPoint(bar: TaiwanCanonicalBarPoint, technicalEligible: boolean): ChartPoint {
  return {
    time: bar.start_at,
    open: numberOrNull(bar.open_price),
    high: numberOrNull(bar.high_price),
    low: numberOrNull(bar.low_price),
    close: numberOrNull(bar.close_price),
    volume: numberOrNull(bar.volume?.value),
    trade_value: numberOrNull(bar.turnover_value),
    transaction_count: bar.trade_count,
    finalization: bar.finalization,
    finalized: bar.finalization !== "provisional",
    is_partial: bar.finalization === "provisional",
    display_eligible: true,
    indicator_eligible: technicalEligible,
    price_semantics: "canonical_bar",
    synthetic: false,
  };
}

export function projectTaiwanBarSeries(series: TaiwanRenderableBarSeries): ChartPoint[] {
  const states = new Map(
    "bar_states" in series
      ? series.bar_states.map((state) => [state.start_at, state.technical_eligible])
      : series.bars.map((bar) => [bar.start_at, bar.technical_eligible])
  );
  return series.bars
    .map((bar) => chartPoint(bar, states.get(bar.start_at) !== false))
    .sort((left, right) => left.time.localeCompare(right.time));
}

function intradayPoints(
  bars: Array<ChartPoint | IntradayTrendPoint>,
  technical: StockIndicatorPoint[]
): IntradayTrendPoint[] {
  const indicatorByTime = new Map(technical.map((point) => [point.time, point]));
  return bars.flatMap((point) => {
    const close = point.close ?? ("price" in point ? point.price : null);
    if (close === null || close === undefined) return [];
    const indicator = indicatorByTime.get(point.time);
    const contract = indicator?.parameter_contract ?? {};
    const emaFast = numberOrNull(
      Array.isArray(contract.macd_fast) ? null : contract.macd_fast
    );
    const emaSlow = numberOrNull(
      Array.isArray(contract.macd_slow) ? null : contract.macd_slow
    );
    const rsiPeriod = numberOrNull(
      Array.isArray(contract.rsi_period) ? null : contract.rsi_period
    );
    return [
      {
        ...point,
        price: close,
        volume: point.volume,
        ema_fast: numberOrNull(
          emaFast === null ? null : indicator?.ema?.[`ema${emaFast}`]
        ),
        ema_slow: numberOrNull(
          emaSlow === null ? null : indicator?.ema?.[`ema${emaSlow}`]
        ),
        rsi_value: numberOrNull(
          rsiPeriod === null ? null : indicator?.rsi?.[`rsi${rsiPeriod}`]
        ),
        macd_value: numberOrNull(indicator?.macd?.macd),
        macd_signal_value: numberOrNull(indicator?.macd?.signal),
        macd_histogram_value: numberOrNull(indicator?.macd?.histogram),
        vwap_value: numberOrNull(indicator?.vwap),
        twap_value: numberOrNull(indicator?.twap),
      },
    ];
  });
}

function chartRequestKey({
  chartFocusMode,
  effectiveTimeframe,
  professionalTimeframe,
  stockId,
  todayInterval,
}: {
  chartFocusMode: boolean;
  effectiveTimeframe: Timeframe;
  professionalTimeframe: ProfessionalTimeframe;
  stockId: string;
  todayInterval: IntradayInterval;
}) {
  const view =
    chartFocusMode && isProfessionalIntradayTimeframe(professionalTimeframe)
      ? `professional:${professionalTimeframe}`
      : effectiveTimeframe === "today"
        ? `today:${todayInterval}m`
        : effectiveTimeframe;
  return `${stockId}:${view}`;
}

function requestInterval(
  chartFocusMode: boolean,
  effectiveTimeframe: Timeframe,
  professionalTimeframe: ProfessionalTimeframe,
  todayInterval: IntradayInterval
) {
  if (chartFocusMode && isProfessionalIntradayTimeframe(professionalTimeframe)) {
    return professionalTimeframe;
  }
  if (effectiveTimeframe === "today") return `${todayInterval}m`;
  return intervalByChartTimeframe[effectiveTimeframe as ChartTimeframe];
}

function requestLimit(
  interval: string,
  effectiveTimeframe: Timeframe,
  isIndexProduct: boolean
) {
  if (interval.endsWith("m") || interval.endsWith("h")) return 5000;
  if (effectiveTimeframe === "daily" && isIndexProduct) {
    return INDEX_DAILY_CHART_BARS;
  }
  return chartBarsByTimeframe[effectiveTimeframe as ChartTimeframe] ?? 500;
}

function chartRefreshIntervalMs(interval: string) {
  const unit = interval.endsWith("h") ? 60 : 1;
  const rawValue = Number(interval.slice(0, -1));
  const bucketMs = Number.isFinite(rawValue)
    ? rawValue * unit * 60_000
    : TAIWAN_CHART_REFRESH_MAX_MS;
  return Math.max(
    TAIWAN_INTRADAY_REFRESH_MS,
    TAIWAN_CHART_REFRESH_MIN_MS,
    Math.min(Math.floor(bucketMs / 4), TAIWAN_CHART_REFRESH_MAX_MS)
  );
}

function mergeTimedPoints<T extends { time: string }>(current: T[], incoming: T[]) {
  const merged = new Map(current.map((point) => [point.time, point]));
  incoming.forEach((point) => merged.set(point.time, point));
  return [...merged.values()].sort((left, right) => left.time.localeCompare(right.time));
}

function validateBars(
  bars: TaiwanRenderableBarSeries,
  instrumentId: string,
  interval: string
) {
  if (
    bars.instrument.symbol !== instrumentId ||
    bars.requested_interval !== interval
  ) {
    throw new Error("Taiwan Bar response identity mismatch");
  }
}

function validateTechnical(
  technical: TaiwanTechnicalSeriesRead,
  bars: TaiwanRenderableBarSeries,
  instrumentId: string,
  interval: string,
  expectedRevision: string,
  snapshotPinned: boolean
) {
  if (
    technical.instrument.symbol !== instrumentId ||
    technical.interval !== interval
  ) {
    throw new Error("Taiwan technical response identity mismatch");
  }
  const returnedRevision = snapshotPinned
    ? technical.bar_snapshot_revision
    : technical.bar_series_revision;
  if (returnedRevision !== expectedRevision) {
    throw new Error("Taiwan technical response revision mismatch");
  }
}

function technicalConsistencyRevision(
  bars: TaiwanRenderableBarSeries,
  currentSession: boolean
) {
  if (currentSession) {
    return bars.current_session_coverage?.snapshot_revision ?? null;
  }
  return bars.identity.series_revision;
}

export function useTaiwanStockChartData({
  chartFocusMode,
  currentStockInfoMarket,
  effectiveTimeframe,
  isIndexProduct,
  professionalTimeframe,
  publishDataStatus,
  reloadNonce,
  stockId,
  t,
  todayInterval,
}: UseTaiwanStockChartDataOptions) {
  const [dailyState, setDailyState] = useState<DailyChartState | null>(null);
  const [benchmarkChartData, setBenchmarkChartData] = useState<ChartPoint[]>([]);
  const [benchmarkChartKey, setBenchmarkChartKey] = useState<string | null>(null);
  const [todayState, setTodayState] = useState<TodayChartState | null>(null);
  const [professionalIntradayData, setProfessionalIntradayData] = useState<ChartPoint[]>([]);
  const [professionalIntradayIndicators, setProfessionalIntradayIndicators] =
    useState<StockIndicatorPoint[]>([]);
  const [professionalIntradayStockId, setProfessionalIntradayStockId] =
    useState<string | null>(null);
  const [professionalIntradayInterval, setProfessionalIntradayInterval] =
    useState<ProfessionalIntradayTimeframe | null>(null);
  const [loadStateScope, setLoadStateScope] = useState<ScopedLoadState | null>(null);
  const [technicalLoadStateScope, setTechnicalLoadStateScope] =
    useState<ScopedLoadState | null>(null);
  const [technicalContract, setTechnicalContract] =
    useState<TaiwanTechnicalCapabilityContract | null>(null);
  const [technicalParameterScope, setTechnicalParameterScope] = useState<{
    requestKey: string;
    contract: Record<string, unknown>;
  } | null>(null);
  const activeStockIdRef = useRef(stockId);
  const todayPresentationCacheRef = useRef(
    new Map<string, TodayPresentationCacheEntry>()
  );
  const tRef = useRef(t);

  const benchmarkIndexId =
    !isIndexProduct && stockId
      ? currentStockInfoMarket === "TPEX"
        ? "TPEX"
        : "TAIEX"
      : null;

  useEffect(() => {
    activeStockIdRef.current = stockId;
  }, [stockId]);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    void fetchJson<TaiwanTechnicalCapabilityContract>(
      "/api/market/technical/contracts/tw"
    )
      .then((contract) => {
        if (!cancelled) setTechnicalContract(contract);
      })
      .catch(() => {
        if (!cancelled) setTechnicalContract(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (stockId) return;
    const timer = window.setTimeout(() => {
      setDailyState(null);
      setTodayState(null);
      setProfessionalIntradayData([]);
      setProfessionalIntradayIndicators([]);
      setLoadStateScope(null);
      setTechnicalLoadStateScope(null);
      setTechnicalParameterScope(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [stockId]);

  useEffect(() => {
    if (!stockId) return;

    const effectStockId = stockId;
    const interval = requestInterval(
      chartFocusMode,
      effectiveTimeframe,
      professionalTimeframe,
      todayInterval
    );
    const effectRequestKey = chartRequestKey({
      chartFocusMode,
      effectiveTimeframe,
      professionalTimeframe,
      stockId: effectStockId,
      todayInterval,
    });
    const professionalIntraday =
      chartFocusMode && isProfessionalIntradayTimeframe(professionalTimeframe);
    const cachedTodayState =
      !professionalIntraday && effectiveTimeframe === "today"
        ? readTodayPresentation(
            todayPresentationCacheRef.current,
            effectStockId,
            interval,
            getMarketCalendarStatusSnapshot("tw")?.presentation_session
              ?.trade_date ?? null
          )
        : null;
    if (cachedTodayState) {
      setTodayState(cachedTodayState);
      setLoadStateScope({ requestKey: effectRequestKey, state: "success" });
    }
    let cancelled = false;
    let refreshTimer: number | undefined;
    let requestInFlight = false;
    let technicalRequestInFlight = false;
    let technicalRevisionInFlight: string | null = null;
    let lastSuccessfulTechnicalRevision: string | null = null;
    let latestBarRevision: string | null = null;
    let exactFullSnapshotRevision: string | null = null;
    let pendingTechnicalBars: TaiwanRenderableBarSeries | null = null;
    let currentTodaySnapshot = cachedTodayState;
    let warmingRetryIndex = 0;

    function requestParams(fullSnapshot: boolean) {
      return {
        interval,
        limit: fullSnapshot
          ? requestLimit(interval, effectiveTimeframe, isIndexProduct)
          : TAIWAN_CHART_REFRESH_LIMIT,
        include_partial: true,
        ...(effectiveTimeframe === "today"
          ? { session_scope: "current_session" }
          : {}),
      };
    }

    async function loadTechnical(
      bars: TaiwanRenderableBarSeries,
      fullSnapshot: boolean
    ) {
      const snapshotPinned = effectiveTimeframe === "today";
      const expectedRevision = technicalConsistencyRevision(
        bars,
        snapshotPinned
      );
      if (!expectedRevision) {
        setTechnicalLoadStateScope({
          requestKey: effectRequestKey,
          state: "error",
        });
        publishDataStatus({
          title: tRef.current("stockDetail.errors.dataLoad"),
          message: "Taiwan technical request is missing its consistency revision",
          source: "技術指標",
        });
        return;
      }
      if (lastSuccessfulTechnicalRevision === expectedRevision) return;
      if (technicalRequestInFlight) {
        if (technicalRevisionInFlight !== expectedRevision) {
          pendingTechnicalBars = bars;
        }
        return;
      }
      technicalRequestInFlight = true;
      technicalRevisionInFlight = expectedRevision;
      setTechnicalLoadStateScope({
        requestKey: effectRequestKey,
        state: "loading",
      });
      try {
        const technical = await fetchJson<TaiwanTechnicalSeriesRead>(
          `/api/market/technical/${effectStockId}/series`,
          {
            ...requestParams(fullSnapshot),
            ...(snapshotPinned
              ? { expected_snapshot_revision: expectedRevision }
              : { expected_series_revision: expectedRevision }),
          }
        );
        if (cancelled || activeStockIdRef.current !== effectStockId) return;
        validateTechnical(
          technical,
          bars,
          effectStockId,
          interval,
          expectedRevision,
          snapshotPinned
        );
        if (latestBarRevision !== expectedRevision) return;
        lastSuccessfulTechnicalRevision = expectedRevision;
        setTechnicalParameterScope({
          requestKey: effectRequestKey,
          contract: technical.parameter_contract ?? {},
        });
        const finalizedIndicators = technical.points ?? [];
        const currentPartialIndicator = technical.current_partial?.point ?? null;
        const indicators = currentPartialIndicator
          ? mergeTimedPoints(finalizedIndicators, [currentPartialIndicator])
          : finalizedIndicators;
        if (professionalIntraday) {
          setProfessionalIntradayIndicators(indicators);
        } else if (effectiveTimeframe === "today") {
          setTodayState((previous) => {
            if (
              previous?.stockId !== effectStockId ||
              previous.interval !== interval
            ) {
              return previous;
            }
            const next = {
              ...previous,
              trend: intradayPoints(previous.trend, indicators),
            };
            rememberTodayPresentation(todayPresentationCacheRef.current, next);
            currentTodaySnapshot = next;
            return next;
          });
        } else {
          setDailyState((previous) =>
            previous?.stockId === effectStockId &&
            previous.timeframe === effectiveTimeframe
              ? { ...previous, indicatorData: indicators }
              : previous
          );
        }
        setTechnicalLoadStateScope({
          requestKey: effectRequestKey,
          state: "success",
        });
        const warnings = [
          ...(technical.warnings ?? []),
          ...(technical.limitations ?? []),
        ];
        if (warnings.length) {
          publishDataStatus({
            level: "warning",
            title: timeframeLabel(tRef.current, effectiveTimeframe),
            message: [...new Set(warnings)].join("；"),
            source: "TaiwanTechnicalService",
          });
        }
      } catch (error) {
        if (cancelled) return;
        setTechnicalLoadStateScope({
          requestKey: effectRequestKey,
          state: "error",
        });
        publishDataStatus({
          title: tRef.current("stockDetail.errors.dataLoad"),
          message:
            error instanceof Error
              ? error.message
              : tRef.current("stockDetail.errors.dataLoad"),
          source: "技術指標",
        });
      } finally {
        technicalRequestInFlight = false;
        technicalRevisionInFlight = null;
        const pending = pendingTechnicalBars;
        pendingTechnicalBars = null;
        if (
          !cancelled &&
          pending &&
          technicalConsistencyRevision(
            pending,
            effectiveTimeframe === "today"
          ) !== lastSuccessfulTechnicalRevision
        ) {
          void loadTechnical(pending, false);
        }
      }
    }

    async function loadChart(showLoading: boolean, fullSnapshot = showLoading) {
      if (requestInFlight) return;
      requestInFlight = true;
      let needsFullRecovery = false;
      let responseSnapshotPhase: TodaySnapshotPhase | null = null;
      const requestedExactRevision = fullSnapshot
        ? exactFullSnapshotRevision
        : null;
      if (showLoading) {
        setLoadStateScope({ requestKey: effectRequestKey, state: "loading" });
      }
      try {
        const series = await fetchJson<TaiwanChartBarSeriesRead>(
          `/api/market/bars/${effectStockId}/chart`,
          {
            ...requestParams(fullSnapshot),
            ...(requestedExactRevision
              ? { expected_snapshot_revision: requestedExactRevision }
              : {}),
          }
        );
        if (cancelled || activeStockIdRef.current !== effectStockId) return;
        validateBars(series, effectStockId, interval);
        latestBarRevision = technicalConsistencyRevision(
          series,
          effectiveTimeframe === "today"
        );
        const presentationTradeDate =
          series.current_session_coverage?.trade_date ?? null;
        if (effectiveTimeframe === "today" && !presentationTradeDate) {
          throw new Error("Taiwan Today chart response is missing current-session identity");
        }
        if (
          requestedExactRevision &&
          series.current_session_coverage?.snapshot_revision !== requestedExactRevision
        ) {
          throw new Error("Taiwan Today exact snapshot response revision mismatch");
        }
        const bars = projectTaiwanBarSeries(series);
        if (
          effectiveTimeframe === "today" &&
          bars.some(
            (point) =>
              point.time.slice(0, 10) !== presentationTradeDate
          )
        ) {
          throw new Error("Taiwan Today chart response contains another trade date");
        }

        if (professionalIntraday) {
          setProfessionalIntradayData((current) =>
            showLoading ? bars : mergeTimedPoints(current, bars)
          );
          if (showLoading) setProfessionalIntradayIndicators([]);
          setProfessionalIntradayStockId(effectStockId);
          setProfessionalIntradayInterval(professionalTimeframe);
        } else if (effectiveTimeframe === "today") {
          const incomingTrend = intradayPoints(bars, []);
          const snapshot = todaySnapshotMetadata(series, {
            fullSnapshot,
            returnedBarCount: bars.length,
          });
          responseSnapshotPhase = snapshot.phase;
          const previous = currentTodaySnapshot;
          const previousMatches =
            previous?.stockId === effectStockId &&
            previous.tradeDate !== null &&
            previous.tradeDate === presentationTradeDate;
          const mergedTrend = previousMatches
            ? mergeTimedPoints(previous.trend, incomingTrend)
            : incomingTrend;
          needsFullRecovery = shouldRecoverTodayFullSnapshot({
            fullSnapshot,
            mergedPointCount: mergedTrend.length,
            returnedPointCount: incomingTrend.length,
            next: snapshot,
            previous: previousMatches ? previous : null,
          });
          if (needsFullRecovery) {
            exactFullSnapshotRevision = snapshot.revision;
          } else if (fullSnapshot) {
            exactFullSnapshotRevision = null;
          }
          const preserveDisplayablePrevious = Boolean(
            previousMatches &&
              previous.snapshotPhase !== "warming" &&
              (snapshot.phase === "warming" || needsFullRecovery)
          );
          const trend =
            snapshot.phase === "warming" && !preserveDisplayablePrevious
              ? emptyIntradayTrendPoints
              : preserveDisplayablePrevious
                ? previous?.trend ?? emptyIntradayTrendPoints
                : fullSnapshot
                  ? incomingTrend
                  : mergedTrend;
          const latest = trend[trend.length - 1] ?? null;
          const nextState: TodayChartState = {
            capabilities: {
              ...missingIntradayCapabilities,
              supports_volume: bars.some((point) => point.volume !== null),
            },
            currentObservation: previousMatches
              ? previous?.currentObservation ?? null
              : null,
            previousClose: previousMatches ? previous?.previousClose ?? null : null,
            priceDiagnostics: previousMatches
              ? previous?.priceDiagnostics ?? null
              : null,
            source: "TaiwanBarService",
            stockId: effectStockId,
            tradeDate: presentationTradeDate,
            trend,
            updatedAt: latest ? formatDateTime(latest.time) : null,
            historyStatus: series.history.history_status,
            interval,
            snapshotPhase: preserveDisplayablePrevious
              ? previous?.snapshotPhase ?? "warming"
              : needsFullRecovery
                ? "warming"
                : snapshot.phase,
            snapshotRevision:
              preserveDisplayablePrevious || needsFullRecovery
                ? previous?.snapshotRevision ?? null
                : snapshot.revision,
            snapshotBarCount:
              preserveDisplayablePrevious || needsFullRecovery
                ? previous?.snapshotBarCount ?? null
                : snapshot.barCount,
            snapshotAvailableFrom:
              preserveDisplayablePrevious || needsFullRecovery
                ? previous?.snapshotAvailableFrom ?? null
                : snapshot.availableFrom,
            snapshotAvailableTo:
              preserveDisplayablePrevious || needsFullRecovery
                ? previous?.snapshotAvailableTo ?? null
                : snapshot.availableTo,
            snapshotReasonCodes:
              preserveDisplayablePrevious || needsFullRecovery
                ? previous?.snapshotReasonCodes ?? []
                : snapshot.reasonCodes,
          };
          if (!needsFullRecovery) {
            rememberTodayPresentation(
              todayPresentationCacheRef.current,
              nextState
            );
          }
          currentTodaySnapshot = nextState;
          setTodayState(nextState);
        } else {
          setDailyState({
            chartData: bars,
            indicatorData: [],
            intradayOverlay: null,
            stockId: effectStockId,
            timeframe: effectiveTimeframe as ChartTimeframe,
            volumeUnit: series.bars.find((bar) => bar.volume)?.volume?.unit ?? null,
          });
        }
        setLoadStateScope({ requestKey: effectRequestKey, state: "success" });
        if (
          effectiveTimeframe !== "today" ||
          (!needsFullRecovery && responseSnapshotPhase !== "warming")
        ) {
          void loadTechnical(series, fullSnapshot);
        }
        const warnings = [
          ...(series.warnings ?? []),
          ...(series.limitations ?? []),
        ];
        if (warnings.length) {
          publishDataStatus({
            level: "warning",
            title: timeframeLabel(tRef.current, effectiveTimeframe),
            message: [...new Set(warnings)].join("；"),
            source: "TaiwanBarService",
          });
        }
      } catch (error) {
        if (cancelled) return;
        if (requestedExactRevision) exactFullSnapshotRevision = null;
        setLoadStateScope({ requestKey: effectRequestKey, state: "error" });
        publishDataStatus({
          title: tRef.current("stockDetail.errors.dataLoad"),
          message:
            error instanceof Error
              ? error.message
              : tRef.current("stockDetail.errors.dataLoad"),
          source: "K 線",
        });
      } finally {
        requestInFlight = false;
        if (cancelled) return;
        if (needsFullRecovery) {
          scheduleChartRequest(0, true);
        } else if (responseSnapshotPhase === "warming") {
          const retryDelay =
            TODAY_WARMING_RETRY_DELAYS_MS[
              Math.min(warmingRetryIndex, TODAY_WARMING_RETRY_DELAYS_MS.length - 1)
            ];
          warmingRetryIndex += 1;
          scheduleChartRequest(retryDelay, false);
        } else {
          warmingRetryIndex = 0;
          scheduleRefresh();
        }
      }
    }

    function scheduleChartRequest(delay: number, fullSnapshot: boolean) {
      if (cancelled || (!professionalIntraday && effectiveTimeframe !== "today")) return;
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(() => {
        void loadChart(false, fullSnapshot);
      }, delay);
    }

    function scheduleRefresh() {
      if (cancelled || (!professionalIntraday && effectiveTimeframe !== "today")) return;
      const marketState = getTaiwanMarketRefreshState();
      const delay = marketState.isPollingWindow
        ? chartRefreshIntervalMs(interval)
        : Math.min(marketState.msUntilNextPollingStart, 60_000);
      scheduleChartRequest(delay, false);
    }

    void loadChart(!cachedTodayState, true);
    return () => {
      cancelled = true;
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
    };
  }, [
    chartFocusMode,
    effectiveTimeframe,
    isIndexProduct,
    professionalTimeframe,
    publishDataStatus,
    reloadNonce,
    stockId,
    todayInterval,
  ]);

  useEffect(() => {
    if (!benchmarkIndexId || effectiveTimeframe === "today") return;
    let cancelled = false;
    const timeframe = effectiveTimeframe as ChartTimeframe;
    const interval = intervalByChartTimeframe[timeframe];
    const requestedKey = `${benchmarkIndexId}:${timeframe}`;

    async function loadBenchmark() {
      try {
        const bars = await fetchJson<TaiwanChartBarSeriesRead>(
          `/api/market/bars/${benchmarkIndexId}/chart`,
          {
            interval,
            limit:
              timeframe === "daily"
                ? INDEX_DAILY_CHART_BARS
                : chartBarsByTimeframe[timeframe],
            include_partial: true,
          }
        );
        if (cancelled || bars.instrument.symbol !== benchmarkIndexId) return;
        setBenchmarkChartData(projectTaiwanBarSeries(bars));
        setBenchmarkChartKey(requestedKey);
      } catch {
        if (cancelled) return;
        setBenchmarkChartData([]);
        setBenchmarkChartKey(null);
      }
    }

    void loadBenchmark();
    return () => {
      cancelled = true;
    };
  }, [benchmarkIndexId, effectiveTimeframe]);

  const currentDailyState =
    stockId !== null && dailyState?.stockId === stockId ? dailyState : null;
  const currentTodayState =
    stockId !== null && todayState?.stockId === stockId ? todayState : null;
  const currentRequestKey = stockId
    ? chartRequestKey({
        chartFocusMode,
        effectiveTimeframe,
        professionalTimeframe,
        stockId,
        todayInterval,
      })
    : null;
  const loadState: LoadState =
    currentRequestKey === null
      ? "idle"
      : loadStateScope?.requestKey === currentRequestKey
        ? loadStateScope.state
        : "loading";
  const technicalLoadState: LoadState =
    currentRequestKey === null
      ? "idle"
      : technicalLoadStateScope?.requestKey === currentRequestKey
        ? technicalLoadStateScope.state
        : "loading";
  const technicalParameterContract =
    currentRequestKey !== null &&
    technicalParameterScope?.requestKey === currentRequestKey
      ? technicalParameterScope.contract
      : null;

  return {
    state: {
      benchmarkChartData,
      benchmarkChartKey,
      benchmarkIndexId,
      chartData: currentDailyState?.chartData ?? emptyChartPoints,
      chartIntradayOverlay: currentDailyState?.intradayOverlay ?? null,
      chartVolumeUnit: currentDailyState?.volumeUnit ?? null,
      chartStockId: currentDailyState?.stockId ?? null,
      chartTimeframe: currentDailyState?.timeframe ?? null,
      indicatorData: currentDailyState?.indicatorData ?? emptyIndicatorPoints,
      loadState,
      professionalIntradayData,
      professionalIntradayIndicators,
      professionalIntradayInterval,
      professionalIntradayStockId,
      todayPreviousClose: currentTodayState?.previousClose ?? null,
      todayCapabilities:
        currentTodayState?.capabilities ?? missingIntradayCapabilities,
      todayCurrentObservation: currentTodayState?.currentObservation ?? null,
      todayHistoryStatus: currentTodayState?.historyStatus ?? "missing",
      todayPriceDiagnostics: currentTodayState?.priceDiagnostics ?? null,
      todaySnapshotPhase: currentTodayState?.snapshotPhase ?? "warming",
      todaySnapshotReasonCodes: currentTodayState?.snapshotReasonCodes ?? [],
      todaySource: currentTodayState?.source ?? "unavailable",
      todayStockId: currentTodayState?.stockId ?? null,
      todayTradeDate: currentTodayState?.tradeDate ?? null,
      todayTrend: currentTodayState?.trend ?? emptyIntradayTrendPoints,
      todayUpdatedAt: currentTodayState?.updatedAt ?? null,
      technicalContract,
      technicalParameterContract,
      technicalLoadState,
    },
  };
}

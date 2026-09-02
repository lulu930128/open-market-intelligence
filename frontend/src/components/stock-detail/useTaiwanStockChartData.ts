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
  TaiwanCanonicalBarPoint,
  TaiwanChartBundleRead,
  TaiwanTechnicalCapabilityContract,
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
  initialChartBundle: TaiwanChartBundleRead | null;
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
};

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

export function projectTaiwanBarSeries(series: TaiwanBarSeriesRead): ChartPoint[] {
  const states = new Map(
    series.bar_states.map((state) => [state.start_at, state.technical_eligible])
  );
  return series.bars
    .map((bar) => chartPoint(bar, states.get(bar.start_at) !== false))
    .sort((left, right) => left.time.localeCompare(right.time));
}

function intradayPoints(
  bars: ChartPoint[],
  technical: StockIndicatorPoint[]
): IntradayTrendPoint[] {
  const indicatorByTime = new Map(technical.map((point) => [point.time, point]));
  return bars.flatMap((point) => {
    if (point.close === null) return [];
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
        price: point.close,
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

function mergeTimedPoints<T extends { time: string }>(current: T[], incoming: T[]) {
  const merged = new Map(current.map((point) => [point.time, point]));
  incoming.forEach((point) => merged.set(point.time, point));
  return [...merged.values()].sort((left, right) => left.time.localeCompare(right.time));
}

function validateBundle(
  bundle: TaiwanChartBundleRead,
  instrumentId: string,
  interval: string
) {
  if (
    bundle.bars.instrument.symbol !== instrumentId ||
    bundle.technical.instrument.symbol !== instrumentId ||
    bundle.bars.requested_interval !== interval ||
    bundle.technical.interval !== interval
  ) {
    throw new Error("Taiwan chart response identity mismatch");
  }
  const revisions = [
    bundle.series_revision,
    bundle.bars.identity.series_revision,
    bundle.technical.bar_series_revision,
  ];
  if (!revisions.every((revision) => revision === revisions[0])) {
    throw new Error("Taiwan chart response revision mismatch");
  }
}

export function useTaiwanStockChartData({
  chartFocusMode,
  currentStockInfoMarket,
  effectiveTimeframe,
  initialChartBundle,
  isIndexProduct,
  professionalTimeframe,
  publishDataStatus,
  reloadNonce,
  stockId,
  t,
  todayInterval,
}: UseTaiwanStockChartDataOptions) {
  const initialDailyState = (() => {
    if (!initialChartBundle || !stockId) return null;
    try {
      validateBundle(initialChartBundle, stockId, "1d");
      return {
        chartData: projectTaiwanBarSeries(initialChartBundle.bars),
        indicatorData: initialChartBundle.technical.points ?? [],
        intradayOverlay: null,
        stockId,
        timeframe: "daily" as const,
        volumeUnit:
          initialChartBundle.bars.bars.find((bar) => bar.volume)?.volume?.unit ?? null,
      } satisfies DailyChartState;
    } catch {
      return null;
    }
  })();
  const [dailyState, setDailyState] = useState<DailyChartState | null>(initialDailyState);
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
  const [loadStateScope, setLoadStateScope] = useState<ScopedLoadState | null>(() =>
    initialDailyState
      ? { requestKey: `${initialDailyState.stockId}:daily`, state: "success" }
      : null
  );
  const [technicalContract, setTechnicalContract] =
    useState<TaiwanTechnicalCapabilityContract | null>(null);
  const activeStockIdRef = useRef(stockId);
  const initialBundleRef = useRef({
    bundle: initialDailyState ? initialChartBundle : null,
    consumed: false,
  });
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
    let cancelled = false;
    let refreshTimer: number | undefined;
    let requestInFlight = false;

    const hydratedBundle = initialBundleRef.current;
    if (
      !hydratedBundle.consumed &&
      hydratedBundle.bundle &&
      interval === "1d" &&
      effectRequestKey === `${effectStockId}:daily`
    ) {
      hydratedBundle.consumed = true;
      setLoadStateScope({ requestKey: effectRequestKey, state: "success" });
      return () => {
        cancelled = true;
      };
    }

    async function loadChart(showLoading: boolean) {
      if (requestInFlight) return;
      requestInFlight = true;
      if (showLoading) {
        setLoadStateScope({ requestKey: effectRequestKey, state: "loading" });
      }
      try {
        const bundle = await fetchJson<TaiwanChartBundleRead>(
          `/api/market/chart/${effectStockId}`,
          {
            interval,
            limit: showLoading
              ? requestLimit(interval, effectiveTimeframe, isIndexProduct)
              : TAIWAN_CHART_REFRESH_LIMIT,
            include_partial: true,
            ma_windows: "5,20,60",
            volume_ma_windows: "5,20",
          }
        );
        if (cancelled || activeStockIdRef.current !== effectStockId) return;
        validateBundle(bundle, effectStockId, interval);
        const bars = projectTaiwanBarSeries(bundle.bars);
        const indicators = bundle.technical.points ?? [];

        if (professionalIntraday) {
          setProfessionalIntradayData((current) =>
            showLoading ? bars : mergeTimedPoints(current, bars)
          );
          setProfessionalIntradayIndicators((current) =>
            showLoading ? indicators : mergeTimedPoints(current, indicators)
          );
          setProfessionalIntradayStockId(effectStockId);
          setProfessionalIntradayInterval(professionalTimeframe);
        } else if (effectiveTimeframe === "today") {
          const incomingTrend = intradayPoints(bars, indicators);
          const quoteSide = bundle.quote_side;
          setTodayState((previous) => {
            const previousMatches = previous?.stockId === effectStockId;
            const trend =
              !showLoading && previousMatches
                ? mergeTimedPoints(previous.trend, incomingTrend)
                : incomingTrend;
            const latest = trend[trend.length - 1] ?? null;
            return {
              capabilities: {
                ...missingIntradayCapabilities,
                ...(quoteSide?.capabilities ?? {}),
                supports_volume:
                  quoteSide?.capabilities?.supports_volume ??
                  bars.some((point) => point.volume !== null),
              },
              currentObservation:
                quoteSide?.current_observation ??
                (previousMatches ? previous.currentObservation : null),
              previousClose:
                quoteSide?.previous_close ?? (previousMatches ? previous.previousClose : null),
              priceDiagnostics:
                quoteSide?.price_diagnostics ??
                (previousMatches ? previous.priceDiagnostics : null),
              source: quoteSide?.source ?? "TaiwanBarService",
              stockId: effectStockId,
              tradeDate: quoteSide?.trade_date ?? latest?.time.slice(0, 10) ?? null,
              trend,
              updatedAt:
                quoteSide?.updated_at ?? (latest ? formatDateTime(latest.time) : null),
              historyStatus: bundle.bars.history.history_status,
            };
          });
        } else {
          setDailyState({
            chartData: bars,
            indicatorData: indicators,
            intradayOverlay: null,
            stockId: effectStockId,
            timeframe: effectiveTimeframe as ChartTimeframe,
            volumeUnit: bundle.bars.bars.find((bar) => bar.volume)?.volume?.unit ?? null,
          });
        }
        setLoadStateScope({ requestKey: effectRequestKey, state: "success" });
        const warnings = [
          ...(bundle.bars.warnings ?? []),
          ...(bundle.bars.limitations ?? []),
          ...(bundle.technical.warnings ?? []),
          ...(bundle.technical.limitations ?? []),
        ];
        if (warnings.length) {
          publishDataStatus({
            level: "warning",
            title: timeframeLabel(tRef.current, effectiveTimeframe),
            message: [...new Set(warnings)].join("；"),
            source: "TaiwanBarService / TaiwanTechnicalService",
          });
        }
      } catch (error) {
        if (cancelled) return;
        setLoadStateScope({ requestKey: effectRequestKey, state: "error" });
        publishDataStatus({
          title: tRef.current("stockDetail.errors.dataLoad"),
          message:
            error instanceof Error
              ? error.message
              : tRef.current("stockDetail.errors.dataLoad"),
          source: "K 線 / 技術指標",
        });
      } finally {
        requestInFlight = false;
      }
    }

    function scheduleRefresh() {
      if (cancelled || (!professionalIntraday && effectiveTimeframe !== "today")) return;
      const marketState = getTaiwanMarketRefreshState();
      const delay = marketState.isPollingWindow
        ? TAIWAN_INTRADAY_REFRESH_MS
        : Math.min(marketState.msUntilNextPollingStart, 60_000);
      refreshTimer = window.setTimeout(() => {
        void loadChart(false).finally(scheduleRefresh);
      }, delay);
    }

    void loadChart(true).finally(scheduleRefresh);
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
        const bars = await fetchJson<TaiwanBarSeriesRead>(
          `/api/market/bars/${benchmarkIndexId}`,
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
      todaySource: currentTodayState?.source ?? "unavailable",
      todayStockId: currentTodayState?.stockId ?? null,
      todayTradeDate: currentTodayState?.tradeDate ?? null,
      todayTrend: currentTodayState?.trend ?? emptyIntradayTrendPoints,
      todayUpdatedAt: currentTodayState?.updatedAt ?? null,
      technicalContract,
    },
  };
}

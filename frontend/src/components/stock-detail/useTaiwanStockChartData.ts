"use client";

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
import type { TaiwanChartTimeframe } from "@/lib/taiwanMarketRules";
import { timeframeLabel, type TranslationFunction } from "@/i18n";
import type {
  ChartPoint,
  IntradayCurrentObservation,
  IntradayHistoryResponse,
  IntradayPriceDiagnostics,
  IntradayTrendCapabilities,
  IntradayTrendPoint,
  IntradayTrendResponse,
  OhlcChartResponse,
  OhlcIntradayOverlay,
  StockIndicatorPoint,
} from "@/types/market";
import { useEffect, useRef, useState } from "react";

const chartBarsByTimeframe: Record<ChartTimeframe, number> = {
  daily: 260,
  weekly: 520,
  monthly: 132,
};
const dailyIndicatorLimit = 240;
const defaultIntradayCapabilities: IntradayTrendCapabilities = {
  supports_volume: true,
  supports_vwap: true,
  supports_price_limit: true,
  supports_quote_depth: true,
};
const emptyChartPoints: ChartPoint[] = [];
const emptyIndicatorPoints: StockIndicatorPoint[] = [];
const emptyIntradayTrendPoints: IntradayTrendPoint[] = [];

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
  initialChartData: ChartPoint[];
  initialChartIntradayOverlay: OhlcIntradayOverlay | null;
  initialChartStockId: string | null;
  initialChartVolumeUnit: string | null;
  initialIndicatorData: StockIndicatorPoint[];
  isIndexProduct: boolean;
  professionalTimeframe: ProfessionalTimeframe;
  publishDataStatus: PublishDataStatus;
  reloadNonce: number;
  stockId: string | null;
  t: TranslationFunction;
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
};

type ScopedLoadState = {
  requestKey: string;
  state: LoadState;
};

function normalizeIsoDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : null;
}

function normalizeChartPoints(points: ChartPoint[]) {
  const pointsByTime = new Map<string, ChartPoint>();

  for (const point of points) {
    const time = String(point.time ?? "").trim();
    if (!time) continue;
    pointsByTime.set(time, point);
  }

  return [...pointsByTime.values()].sort((left, right) =>
    String(left.time).localeCompare(String(right.time))
  );
}

function shouldIncludeTaiwanOhlcIntraday() {
  const marketState = getTaiwanMarketRefreshState();
  return (
    marketState.isPollingWindow ||
    (marketState.isAfterClose && !marketState.isDailyPriceReleased)
  );
}

function latestOhlcDate(ohlc: OhlcChartResponse) {
  return normalizeIsoDate(ohlc.points[ohlc.points.length - 1]?.time);
}

function shouldRetryTaiwanDailyOhlcWithIntraday(ohlc: OhlcChartResponse) {
  const marketState = getTaiwanMarketRefreshState();
  if (!marketState.isAfterClose || !marketState.isDailyPriceReleased) return false;

  const latestDate = latestOhlcDate(ohlc);
  return latestDate === null || latestDate < marketState.dateKey;
}

function chartRequestKey({
  chartFocusMode,
  effectiveTimeframe,
  professionalTimeframe,
  stockId,
}: {
  chartFocusMode: boolean;
  effectiveTimeframe: Timeframe;
  professionalTimeframe: ProfessionalTimeframe;
  stockId: string;
}) {
  const view =
    chartFocusMode && isProfessionalIntradayTimeframe(professionalTimeframe)
      ? `professional:${professionalTimeframe}`
      : effectiveTimeframe;
  return `${stockId}:${view}`;
}

function assertOhlcIdentity(
  ohlc: OhlcChartResponse,
  stockId: string,
  timeframe: ChartTimeframe
) {
  if (ohlc.stock_id !== stockId || ohlc.timeframe !== timeframe) {
    throw new Error(
      `OHLC response identity mismatch: expected ${stockId}/${timeframe}, received ${ohlc.stock_id}/${ohlc.timeframe}`
    );
  }
}

export function useTaiwanStockChartData({
  chartFocusMode,
  currentStockInfoMarket,
  effectiveTimeframe,
  initialChartData,
  initialChartIntradayOverlay,
  initialChartStockId,
  initialChartVolumeUnit,
  initialIndicatorData,
  isIndexProduct,
  professionalTimeframe,
  publishDataStatus,
  reloadNonce,
  stockId,
  t,
}: UseTaiwanStockChartDataOptions) {
  const initialDailyPayloadMatches =
    stockId !== null &&
    initialChartStockId === stockId &&
    initialChartData.length > 0;
  const [dailyState, setDailyState] = useState<DailyChartState | null>(() =>
    initialDailyPayloadMatches
      ? {
          chartData: normalizeChartPoints(initialChartData),
          indicatorData: initialIndicatorData,
          intradayOverlay: initialChartIntradayOverlay,
          stockId,
          timeframe: "daily",
          volumeUnit: initialChartVolumeUnit,
        }
      : null
  );
  const [benchmarkChartData, setBenchmarkChartData] = useState<ChartPoint[]>([]);
  const [benchmarkChartKey, setBenchmarkChartKey] = useState<string | null>(null);
  const [todayState, setTodayState] = useState<TodayChartState | null>(null);
  const [professionalIntradayData, setProfessionalIntradayData] = useState<ChartPoint[]>([]);
  const [professionalIntradayStockId, setProfessionalIntradayStockId] =
    useState<string | null>(null);
  const [professionalIntradayInterval, setProfessionalIntradayInterval] =
    useState<ProfessionalIntradayTimeframe | null>(null);
  const [professionalIntradayFallbackActive, setProfessionalIntradayFallbackActive] =
    useState(false);
  const [loadStateScope, setLoadStateScope] = useState<ScopedLoadState | null>(() =>
    initialDailyPayloadMatches && stockId
      ? {
          requestKey: chartRequestKey({
            chartFocusMode,
            effectiveTimeframe: "daily",
            professionalTimeframe,
            stockId,
          }),
          state: "success",
        }
      : null
  );
  const finalIntradayRefreshDateRef = useRef<string | null>(null);
  const activeStockIdRef = useRef(stockId);
  const initialDailyStockIdRef = useRef(
    initialDailyPayloadMatches ? initialChartStockId : null
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
    if (stockId) return;

    const timer = window.setTimeout(() => {
      setDailyState(null);
      setTodayState(null);
      setLoadStateScope(null);
    }, 0);

    return () => window.clearTimeout(timer);
  }, [stockId]);

  useEffect(() => {
    if (!stockId) return;

    const effectStockId = stockId;
    const effectRequestKey = chartRequestKey({
      chartFocusMode,
      effectiveTimeframe,
      professionalTimeframe,
      stockId: effectStockId,
    });
    let cancelled = false;
    let intradayTimer: number | undefined;
    let intradayRequestInFlight = false;
    const shouldLoadProfessionalIntraday =
      chartFocusMode &&
      !isIndexProduct &&
      isProfessionalIntradayTimeframe(professionalTimeframe);

    function clearIntradayTimer() {
      if (intradayTimer !== undefined) {
        window.clearTimeout(intradayTimer);
        intradayTimer = undefined;
      }
    }

    async function loadTodayTrend(showLoading: boolean) {
      if (intradayRequestInFlight) return;
      intradayRequestInFlight = true;

      if (showLoading) {
        setLoadStateScope({ requestKey: effectRequestKey, state: "loading" });
      }

      try {
        const today = await fetchJson<IntradayTrendResponse>(
          isIndexProduct
            ? `/api/market/indices/${effectStockId}/intraday`
            : `/api/market/intraday/${effectStockId}`
        );
        if (cancelled || activeStockIdRef.current !== effectStockId) return;
        if (today.stock_id !== effectStockId) {
          throw new Error(
            `Intraday response identity mismatch: expected ${effectStockId}, received ${today.stock_id}`
          );
        }

        const latestPoint = today.points[today.points.length - 1] ?? null;
        const updatedAt = today.current_observation?.observed_at
            ? formatDateTime(today.current_observation.observed_at)
            : latestPoint
              ? formatDateTime(latestPoint.time)
              : null;
        const priceDiagnostics =
          today.current_trade_available !== undefined ||
            today.history_price_source !== undefined
            ? {
                history_price_source: today.history_price_source ?? null,
                latest_history_time: today.latest_history_time ?? null,
                latest_history_price: today.latest_history_price ?? null,
                latest_actual_trade_time: today.latest_actual_trade_time ?? null,
                latest_actual_trade_price: today.latest_actual_trade_price ?? null,
                current_price_source: today.current_price_source ?? null,
                lag_seconds: today.lag_seconds ?? null,
                current_trade_available: today.current_trade_available ?? false,
                current_trade_unavailable_reason:
                  today.current_trade_unavailable_reason ?? null,
                current_price_applied_to_history:
                  today.current_price_applied_to_history ?? false,
              }
            : null;
        setTodayState({
          capabilities: today.capabilities ?? defaultIntradayCapabilities,
          currentObservation: today.current_observation ?? null,
          previousClose: today.previous_close,
          priceDiagnostics,
          source: today.source,
          stockId: effectStockId,
          tradeDate: today.trade_date ?? null,
          trend: today.points,
          updatedAt,
        });
        setLoadStateScope({ requestKey: effectRequestKey, state: "success" });
        if (today.warnings?.length) {
          publishDataStatus({
            level: "warning",
            title: timeframeLabel(tRef.current, "today"),
            message: today.warnings.join("；"),
            source: today.source,
          });
        }
      } catch (error) {
        if (cancelled) return;
        setLoadStateScope({ requestKey: effectRequestKey, state: "error" });
        const message =
          error instanceof Error ? error.message : tRef.current("stockDetail.errors.dataLoad");
        publishDataStatus({
          title: tRef.current("stockDetail.errors.dataLoad"),
          message,
          source: "今日走勢",
        });
      } finally {
        intradayRequestInFlight = false;
      }
    }

    async function loadProfessionalIntradayHistory() {
      if (!isProfessionalIntradayTimeframe(professionalTimeframe)) return;

      setLoadStateScope({ requestKey: effectRequestKey, state: "loading" });
      setProfessionalIntradayData([]);
      setProfessionalIntradayStockId(effectStockId);
      setProfessionalIntradayInterval(professionalTimeframe);
      setProfessionalIntradayFallbackActive(false);

      try {
        const history = await fetchJson<IntradayHistoryResponse>(
          `/api/market/intraday/${effectStockId}/history`,
          { interval: professionalTimeframe, range: "auto", refresh: false }
        );

        if (cancelled || activeStockIdRef.current !== effectStockId) return;
        if (
          history.stock_id !== effectStockId ||
          history.interval !== professionalTimeframe
        ) {
          throw new Error(
            `Intraday history identity mismatch: expected ${effectStockId}/${professionalTimeframe}, received ${history.stock_id}/${history.interval}`
          );
        }

        if (history.points.length === 0) {
          await loadTodayTrend(false);
          if (cancelled || activeStockIdRef.current !== effectStockId) return;

          setProfessionalIntradayFallbackActive(true);
          const message = tRef.current("stockDetail.errors.intradayHistoryFallbackNoData");
          publishDataStatus({
            level: "warning",
            title: tRef.current("stockDetail.errors.intradayHistoryFallbackNoData"),
            message,
            source: "K 線 / 技術指標",
          });
          return;
        }

        setProfessionalIntradayData(history.points);
        setProfessionalIntradayStockId(effectStockId);
        setProfessionalIntradayInterval(professionalTimeframe);
        setProfessionalIntradayFallbackActive(false);
        setLoadStateScope({ requestKey: effectRequestKey, state: "success" });
      } catch (error) {
        if (cancelled || activeStockIdRef.current !== effectStockId) return;

        setProfessionalIntradayData([]);
        setProfessionalIntradayStockId(effectStockId);
        setProfessionalIntradayInterval(professionalTimeframe);
        await loadTodayTrend(false);
        if (cancelled || activeStockIdRef.current !== effectStockId) return;

        setProfessionalIntradayFallbackActive(true);
        const message =
          error instanceof Error
            ? tRef.current("stockDetail.errors.intradayHistoryFallbackFailedWithMessage", {
                message: error.message,
              })
            : tRef.current("stockDetail.errors.intradayHistoryFallbackFailed");
        publishDataStatus({
          level: "warning",
          title: tRef.current("stockDetail.errors.intradayHistoryFallbackFailed"),
          message,
          source: "K 線 / 技術指標",
        });
      }
    }

    function scheduleTodayRefresh() {
      if (cancelled) return;
      const marketState = getTaiwanMarketRefreshState();

      if (marketState.isPollingWindow) {
        intradayTimer = window.setTimeout(() => {
          void loadTodayTrend(false).finally(scheduleTodayRefresh);
        }, TAIWAN_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalIntradayRefreshDateRef.current !== marketState.dateKey
      ) {
        finalIntradayRefreshDateRef.current = marketState.dateKey;
        intradayTimer = window.setTimeout(() => {
          void loadTodayTrend(false).finally(scheduleTodayRefresh);
        }, 0);
        return;
      }

      intradayTimer = window.setTimeout(
        scheduleTodayRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    async function loadChart() {
      if (shouldLoadProfessionalIntraday) {
        await loadProfessionalIntradayHistory();
        return;
      }

      if (effectiveTimeframe === "today") {
        await loadTodayTrend(true);
        if (!cancelled) {
          const marketState = getTaiwanMarketRefreshState();
          if (marketState.isAfterClose) {
            finalIntradayRefreshDateRef.current = marketState.dateKey;
          }
          scheduleTodayRefresh();
        }
        return;
      }

      setLoadStateScope({ requestKey: effectRequestKey, state: "loading" });

      try {
        const requestedTimeframe = effectiveTimeframe as TaiwanChartTimeframe;
        const chartBars = chartBarsByTimeframe[requestedTimeframe];
        const includeIntraday = !isIndexProduct && shouldIncludeTaiwanOhlcIntraday();
        const ohlcParams = {
          timeframe: requestedTimeframe,
          bars: chartBars,
          ensure_history: false,
          ...(includeIntraday ? { include_intraday: true } : {}),
        };
        const [initialOhlc, indicators] = await Promise.all([
          fetchJson<OhlcChartResponse>(
            isIndexProduct
              ? `/api/market/indices/${effectStockId}/ohlc`
              : `/api/market/ohlc/${effectStockId}`,
            ohlcParams
          ),
          isIndexProduct
            ? Promise.resolve<StockIndicatorPoint[]>([])
            : fetchJson<StockIndicatorPoint[]>(
                `/api/market/indicators/${effectStockId}/daily`,
                {
                  limit: dailyIndicatorLimit,
                  ma_windows: "5,20,60",
                  volume_ma_windows: "5,20",
                }
              ),
        ]);
        let ohlc = initialOhlc;
        assertOhlcIdentity(ohlc, effectStockId, requestedTimeframe);

        if (
          requestedTimeframe === "daily" &&
          !includeIntraday &&
          !isIndexProduct &&
          shouldRetryTaiwanDailyOhlcWithIntraday(ohlc)
        ) {
          ohlc = await fetchJson<OhlcChartResponse>(
            `/api/market/ohlc/${effectStockId}`,
            {
              timeframe: requestedTimeframe,
              bars: chartBars,
              ensure_history: false,
              include_intraday: true,
            }
          );
          assertOhlcIdentity(ohlc, effectStockId, requestedTimeframe);
        }
        if (cancelled || activeStockIdRef.current !== effectStockId) return;
        setDailyState({
          chartData: normalizeChartPoints(ohlc.points),
          indicatorData: indicators,
          intradayOverlay: ohlc.intraday_overlay,
          stockId: effectStockId,
          timeframe: requestedTimeframe,
          volumeUnit: ohlc.volume_unit ?? null,
        });
        setLoadStateScope({ requestKey: effectRequestKey, state: "success" });
        if (ohlc.warnings?.length) {
          publishDataStatus({
            level: "warning",
            title: timeframeLabel(tRef.current, requestedTimeframe),
            message: ohlc.warnings.join("；"),
            source: "index_ohlc",
          });
        }

      } catch (error) {
        if (cancelled) return;
        setLoadStateScope({ requestKey: effectRequestKey, state: "error" });
        const message =
          error instanceof Error ? error.message : tRef.current("stockDetail.errors.dataLoad");
        publishDataStatus({
          title: tRef.current("stockDetail.errors.dataLoad"),
          message,
          source: "K 線 / 技術指標",
        });
      }
    }

    const canReuseInitialDaily =
      !shouldLoadProfessionalIntraday &&
      effectiveTimeframe === "daily" &&
      reloadNonce === 0 &&
      initialDailyStockIdRef.current === effectStockId;
    initialDailyStockIdRef.current = null;
    if (!canReuseInitialDaily) {
      void loadChart();
    }
    return () => {
      cancelled = true;
      clearIntradayTimer();
    };
  }, [
    chartFocusMode,
    effectiveTimeframe,
    isIndexProduct,
    professionalTimeframe,
    publishDataStatus,
    reloadNonce,
    stockId,
  ]);

  useEffect(() => {
    if (!benchmarkIndexId || effectiveTimeframe === "today") return;

    let cancelled = false;
    const requestedIndexId = benchmarkIndexId;
    const requestedTimeframe = effectiveTimeframe as ChartTimeframe;
    const requestedKey = `${requestedIndexId}:${requestedTimeframe}`;

    async function loadBenchmarkChart() {
      try {
        const ohlc = await fetchJson<OhlcChartResponse>(
          `/api/market/indices/${requestedIndexId}/ohlc`,
          {
            timeframe: requestedTimeframe,
            bars: chartBarsByTimeframe[requestedTimeframe],
            ensure_history: false,
          }
        );
        if (cancelled) return;
        assertOhlcIdentity(ohlc, requestedIndexId, requestedTimeframe);

        setBenchmarkChartData(normalizeChartPoints(ohlc.points));
        setBenchmarkChartKey(requestedKey);
      } catch {
        if (cancelled) return;
        setBenchmarkChartData([]);
        setBenchmarkChartKey(null);
      }
    }

    void loadBenchmarkChart();
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
      professionalIntradayFallbackActive,
      professionalIntradayInterval,
      professionalIntradayStockId,
      todayPreviousClose: currentTodayState?.previousClose ?? null,
      todayCapabilities:
        currentTodayState?.capabilities ?? defaultIntradayCapabilities,
      todayCurrentObservation: currentTodayState?.currentObservation ?? null,
      todayPriceDiagnostics: currentTodayState?.priceDiagnostics ?? null,
      todaySource: currentTodayState?.source ?? "unavailable",
      todayStockId: currentTodayState?.stockId ?? null,
      todayTradeDate: currentTodayState?.tradeDate ?? null,
      todayTrend: currentTodayState?.trend ?? emptyIntradayTrendPoints,
      todayUpdatedAt: currentTodayState?.updatedAt ?? null,
    },
  };
}

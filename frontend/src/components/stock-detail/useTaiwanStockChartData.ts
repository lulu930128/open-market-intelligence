"use client";

import {
  formatDateTime,
  isProfessionalIntradayTimeframe,
  shiftIsoDate,
  type ChartTimeframe,
  type LoadState,
  type ProfessionalIntradayTimeframe,
  type ProfessionalTimeframe,
  type Timeframe,
} from "@/components/stock-detail/StockDetailDataViews";
import { fetchJson, requestJson } from "@/lib/api";
import type { DataStatusLevel } from "@/lib/dataStatusEvents";
import { requestBackfillJob } from "@/lib/jobs";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  getTaiwanMarketRefreshState,
} from "@/lib/taiwanMarketTime";
import {
  getTaiwanChartHistoryRequirement,
  taiwanDailyPriceBackfillPath,
  type TaiwanChartTimeframe,
} from "@/lib/taiwanMarketRules";
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
  StockMasterRead,
} from "@/types/market";
import { useEffect, useRef, useState } from "react";

const chartBarsByTimeframe: Record<ChartTimeframe, number> = {
  daily: 2_600,
  weekly: 520,
  monthly: 132,
};
const dailyIndicatorLimit = 220;
const defaultIntradayCapabilities: IntradayTrendCapabilities = {
  supports_volume: true,
  supports_vwap: true,
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
  currentStockInfoId: string | null;
  currentStockInfoMarket: string | null;
  effectiveTimeframe: Timeframe;
  initialChartData: ChartPoint[];
  initialChartIntradayOverlay: OhlcIntradayOverlay | null;
  initialChartVolumeUnit: string | null;
  initialIndicatorData: StockIndicatorPoint[];
  isIndexProduct: boolean;
  onDailyPricesChanged?: () => void;
  onStockInfoResolved: (stock: StockMasterRead) => void;
  professionalTimeframe: ProfessionalTimeframe;
  publishDataStatus: PublishDataStatus;
  reloadNonce: number;
  stockId: string | null;
  subresourceRefreshSeconds: number;
  t: TranslationFunction;
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

export function useTaiwanStockChartData({
  chartFocusMode,
  currentStockInfoId,
  currentStockInfoMarket,
  effectiveTimeframe,
  initialChartData,
  initialChartIntradayOverlay,
  initialChartVolumeUnit,
  initialIndicatorData,
  isIndexProduct,
  onDailyPricesChanged,
  onStockInfoResolved,
  professionalTimeframe,
  publishDataStatus,
  reloadNonce,
  stockId,
  subresourceRefreshSeconds,
  t,
}: UseTaiwanStockChartDataOptions) {
  const [chartData, setChartData] = useState<ChartPoint[]>(
    normalizeChartPoints(initialChartData)
  );
  const [chartIntradayOverlay, setChartIntradayOverlay] =
    useState<OhlcIntradayOverlay | null>(initialChartIntradayOverlay);
  const [chartVolumeUnit, setChartVolumeUnit] = useState<string | null>(
    initialChartVolumeUnit
  );
  const [chartStockId, setChartStockId] = useState<string | null>(stockId);
  const [chartTimeframe, setChartTimeframe] = useState<ChartTimeframe>("daily");
  const [benchmarkChartData, setBenchmarkChartData] = useState<ChartPoint[]>([]);
  const [benchmarkChartKey, setBenchmarkChartKey] = useState<string | null>(null);
  const [todayTrend, setTodayTrend] = useState<IntradayTrendPoint[]>([]);
  const [todayPreviousClose, setTodayPreviousClose] = useState<number | null>(null);
  const [todaySource, setTodaySource] = useState("unavailable");
  const [todayTradeDate, setTodayTradeDate] = useState<string | null>(null);
  const [todayUpdatedAt, setTodayUpdatedAt] = useState<string | null>(null);
  const [todayCapabilities, setTodayCapabilities] =
    useState<IntradayTrendCapabilities>(defaultIntradayCapabilities);
  const [todayCurrentObservation, setTodayCurrentObservation] =
    useState<IntradayCurrentObservation | null>(null);
  const [todayPriceDiagnostics, setTodayPriceDiagnostics] =
    useState<IntradayPriceDiagnostics | null>(null);
  const [professionalIntradayData, setProfessionalIntradayData] = useState<ChartPoint[]>([]);
  const [professionalIntradayStockId, setProfessionalIntradayStockId] =
    useState<string | null>(null);
  const [professionalIntradayInterval, setProfessionalIntradayInterval] =
    useState<ProfessionalIntradayTimeframe | null>(null);
  const [professionalIntradayFallbackActive, setProfessionalIntradayFallbackActive] =
    useState(false);
  const [indicatorData, setIndicatorData] = useState<StockIndicatorPoint[]>(
    initialIndicatorData
  );
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const finalIntradayRefreshDateRef = useRef<string | null>(null);
  const activeStockIdRef = useRef(stockId);
  const chartHistoryBackfillKeysRef = useRef(new Set<string>());
  const chartHistoryIssueKeysRef = useRef(new Set<string>());
  const onDailyPricesChangedRef = useRef(onDailyPricesChanged);
  const subresourceRefreshSecondsRef = useRef(subresourceRefreshSeconds);
  const tRef = useRef(t);

  const benchmarkIndexId =
    !isIndexProduct && stockId
      ? currentStockInfoMarket === "TPEX"
        ? "TPEX"
        : "TAIEX"
      : null;

  useEffect(() => {
    activeStockIdRef.current = stockId;
    chartHistoryBackfillKeysRef.current.clear();
    chartHistoryIssueKeysRef.current.clear();
  }, [stockId]);

  useEffect(() => {
    subresourceRefreshSecondsRef.current = subresourceRefreshSeconds;
  }, [subresourceRefreshSeconds]);

  useEffect(() => {
    onDailyPricesChangedRef.current = onDailyPricesChanged;
  }, [onDailyPricesChanged]);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    if (stockId) return;

    const timer = window.setTimeout(() => {
      setChartData([]);
      setChartIntradayOverlay(null);
      setChartVolumeUnit(null);
      setChartStockId(null);
      setChartTimeframe("daily");
      setTodayTrend([]);
      setTodayPreviousClose(null);
      setTodaySource("unavailable");
      setTodayTradeDate(null);
      setTodayUpdatedAt(null);
      setTodayCapabilities(defaultIntradayCapabilities);
      setTodayCurrentObservation(null);
      setTodayPriceDiagnostics(null);
      setIndicatorData([]);
      setLoadState("idle");
    }, 0);

    return () => window.clearTimeout(timer);
  }, [stockId]);

  useEffect(() => {
    if (!stockId) return;

    const effectStockId = stockId;
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

    async function refreshTodayIntradayCache() {
      if (isIndexProduct) return;
      await requestJson<IntradayHistoryResponse>(
        `/api/market/intraday/${effectStockId}/history/refresh`,
        { method: "POST" },
        { interval: "1m", range: "1d", policy: "prefer_live" }
      );
    }

    async function loadTodayTrend(showLoading: boolean) {
      if (intradayRequestInFlight) return;
      intradayRequestInFlight = true;

      if (showLoading) {
        setLoadState("loading");
        setTodayUpdatedAt(null);
        setTodayCapabilities(defaultIntradayCapabilities);
        setTodayCurrentObservation(null);
      }

      try {
        if (!isIndexProduct) {
          try {
            await refreshTodayIntradayCache();
          } catch (error) {
            if (!cancelled) {
              publishDataStatus({
                level: "warning",
                title: timeframeLabel(tRef.current, "today"),
                message:
                  error instanceof Error
                    ? error.message
                    : tRef.current("stockDetail.errors.dataLoad"),
                source: "今日走勢",
                statusKey: "today-intraday-refresh",
              });
            }
          }
        }

        const today = await fetchJson<IntradayTrendResponse>(
          isIndexProduct
            ? `/api/market/indices/${effectStockId}/intraday`
            : `/api/market/intraday/${effectStockId}`
        );
        if (cancelled) return;

        setTodayTrend(today.points);
        setTodayPreviousClose(today.previous_close);
        setTodaySource(today.source);
        setTodayTradeDate(today.trade_date ?? null);
        setTodayCapabilities(today.capabilities ?? defaultIntradayCapabilities);
        setTodayCurrentObservation(today.current_observation ?? null);
        const latestPoint = today.points[today.points.length - 1] ?? null;
        setTodayUpdatedAt(
          today.current_observation?.observed_at
            ? formatDateTime(today.current_observation.observed_at)
            : latestPoint
              ? formatDateTime(latestPoint.time)
              : null
        );
        setTodayPriceDiagnostics(
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
            : null
        );
        setLoadState("success");
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
        setLoadState("error");
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

      setLoadState("loading");
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
        setLoadState("success");
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

    async function resolveStockMarketForBackfill(targetStockId: string) {
      if (currentStockInfoId === targetStockId) return currentStockInfoMarket;

      try {
        const stockData = await fetchJson<StockMasterRead>(`/api/stocks/${targetStockId}`);
        if (!cancelled && activeStockIdRef.current === targetStockId) {
          onStockInfoResolved(stockData);
        }
        return stockData.market;
      } catch {
        return null;
      }
    }

    async function maybeQueueChartHistoryBackfill(
      targetStockId: string,
      requestedTimeframe: TaiwanChartTimeframe,
      ohlc: OhlcChartResponse
    ) {
      const requirement = getTaiwanChartHistoryRequirement(requestedTimeframe);
      const requirementLabel = timeframeLabel(tRef.current, requestedTimeframe);
      const statusKey = `chart-history:${requestedTimeframe}`;
      const statusSource = "K 線 / 技術指標";

      function publishChartHistoryStatus({
        level,
        message,
      }: {
        level: DataStatusLevel;
        message: string;
      }) {
        publishDataStatus({
          level,
          title: requirementLabel,
          message,
          source: statusSource,
          statusKey,
        });

        if (level === "warning" || level === "error") {
          chartHistoryIssueKeysRef.current.add(statusKey);
        } else {
          chartHistoryIssueKeysRef.current.delete(statusKey);
        }
      }

      if (ohlc.point_count >= requirement.minPoints) {
        if (chartHistoryIssueKeysRef.current.has(statusKey)) {
          publishChartHistoryStatus({
            level: "success",
            message: tRef.current("stockDetail.chartHistory.complete", {
              label: requirementLabel,
            }),
          });
        }
        return;
      }

      const market = await resolveStockMarketForBackfill(targetStockId);
      const backfillPath = taiwanDailyPriceBackfillPath(targetStockId, market);
      if (!backfillPath) {
        if (!cancelled && activeStockIdRef.current === targetStockId) {
          publishChartHistoryStatus({
            level: "warning",
            message: tRef.current("stockDetail.chartHistory.depthUnsupported", {
              label: requirementLabel,
              market: market ?? "-",
            }),
          });
        }
        return;
      }

      const endDate = ohlc.to_date.slice(0, 10);
      const startDate = shiftIsoDate(endDate, -requirement.lookbackDays);
      const backfillKey = `${targetStockId}:${requestedTimeframe}:${startDate}:${endDate}`;
      if (chartHistoryBackfillKeysRef.current.has(backfillKey)) return;

      chartHistoryBackfillKeysRef.current.add(backfillKey);
      let jobObserved = false;
      let backfillCompleted = false;

      try {
        await requestBackfillJob(
          backfillPath,
          { method: "POST" },
          {
            start_date: startDate,
            end_date: endDate,
            sleep_seconds: subresourceRefreshSecondsRef.current,
            skip_existing_months: true,
          },
          {
            intervalMs: 2_000,
            timeoutMs: 900_000,
            onUpdate: () => {
              jobObserved = true;
            },
          }
        );
        backfillCompleted = true;

        const refreshedOhlc = await fetchJson<OhlcChartResponse>(
          `/api/market/ohlc/${targetStockId}`,
          {
            timeframe: requestedTimeframe,
            bars: chartBarsByTimeframe[requestedTimeframe],
            ensure_history: false,
            include_intraday: shouldIncludeTaiwanOhlcIntraday(),
          }
        );
        const refreshedIndicators = await fetchJson<StockIndicatorPoint[]>(
          `/api/market/indicators/${targetStockId}/daily`,
          {
            limit: dailyIndicatorLimit,
            ma_windows: "5,20,60",
            volume_ma_windows: "5,20",
          }
        );

        if (cancelled || activeStockIdRef.current !== targetStockId) return;

        setChartData(normalizeChartPoints(refreshedOhlc.points));
        setChartIntradayOverlay(refreshedOhlc.intraday_overlay);
        setChartVolumeUnit(refreshedOhlc.volume_unit ?? null);
        setIndicatorData(refreshedIndicators);
        setChartStockId(targetStockId);
        setChartTimeframe(requestedTimeframe);
        onDailyPricesChangedRef.current?.();
        if (refreshedOhlc.point_count < requirement.minPoints) {
          publishChartHistoryStatus({
            level: "warning",
            message: tRef.current("stockDetail.chartHistory.completeWithCount", {
              label: requirementLabel,
              count: refreshedOhlc.point_count,
            }),
          });
        } else if (chartHistoryIssueKeysRef.current.has(statusKey)) {
          publishChartHistoryStatus({
            level: "success",
            message: tRef.current("stockDetail.chartHistory.complete", {
              label: requirementLabel,
            }),
          });
        }
      } catch (error) {
        if (cancelled || activeStockIdRef.current !== targetStockId) return;
        if (!jobObserved || backfillCompleted) {
          publishChartHistoryStatus({
            level: "error",
            message:
              error instanceof Error
                ? error.message
                : tRef.current("stockDetail.errors.dataLoad"),
          });
        }
      }
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

      setLoadState("loading");

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
        let ohlc = await fetchJson<OhlcChartResponse>(
          isIndexProduct
            ? `/api/market/indices/${effectStockId}/ohlc`
            : `/api/market/ohlc/${effectStockId}`,
          ohlcParams
        );

        if (
          requestedTimeframe === "daily" &&
          !includeIntraday &&
          !isIndexProduct &&
          shouldRetryTaiwanDailyOhlcWithIntraday(ohlc)
        ) {
          try {
            await refreshTodayIntradayCache();
          } catch (error) {
            publishDataStatus({
              level: "warning",
              title: timeframeLabel(tRef.current, "today"),
              message:
                error instanceof Error
                  ? error.message
                  : tRef.current("stockDetail.errors.dataLoad"),
              source: "今日走勢",
              statusKey: "today-intraday-refresh",
            });
          }
          ohlc = await fetchJson<OhlcChartResponse>(
            `/api/market/ohlc/${effectStockId}`,
            {
              timeframe: requestedTimeframe,
              bars: chartBars,
              ensure_history: false,
              include_intraday: true,
            }
          );
        }

        const indicators = isIndexProduct
          ? []
          : await fetchJson<StockIndicatorPoint[]>(
              `/api/market/indicators/${effectStockId}/daily`,
              {
                limit: dailyIndicatorLimit,
                ma_windows: "5,20,60",
                volume_ma_windows: "5,20",
              }
            );
        if (cancelled) return;

        setChartData(normalizeChartPoints(ohlc.points));
        setChartIntradayOverlay(ohlc.intraday_overlay);
        setChartVolumeUnit(ohlc.volume_unit ?? null);
        setIndicatorData(indicators);
        setChartStockId(effectStockId);
        setChartTimeframe(requestedTimeframe);
        setLoadState("success");
        if (ohlc.warnings?.length) {
          publishDataStatus({
            level: "warning",
            title: timeframeLabel(tRef.current, requestedTimeframe),
            message: ohlc.warnings.join("；"),
            source: "index_ohlc",
          });
        }

        if (!isIndexProduct) {
          void maybeQueueChartHistoryBackfill(effectStockId, requestedTimeframe, ohlc);
        }
      } catch (error) {
        if (cancelled) return;
        setLoadState("error");
        const message =
          error instanceof Error ? error.message : tRef.current("stockDetail.errors.dataLoad");
        publishDataStatus({
          title: tRef.current("stockDetail.errors.dataLoad"),
          message,
          source: "K 線 / 技術指標",
        });
      }
    }

    void loadChart();
    return () => {
      cancelled = true;
      clearIntradayTimer();
    };
  }, [
    chartFocusMode,
    currentStockInfoId,
    currentStockInfoMarket,
    effectiveTimeframe,
    isIndexProduct,
    onStockInfoResolved,
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

  return {
    state: {
      benchmarkChartData,
      benchmarkChartKey,
      benchmarkIndexId,
      chartData,
      chartIntradayOverlay,
      chartVolumeUnit,
      chartStockId,
      chartTimeframe,
      indicatorData,
      loadState,
      professionalIntradayData,
      professionalIntradayFallbackActive,
      professionalIntradayInterval,
      professionalIntradayStockId,
      todayPreviousClose,
      todayCapabilities,
      todayCurrentObservation,
      todayPriceDiagnostics,
      todaySource,
      todayTradeDate,
      todayTrend,
      todayUpdatedAt,
    },
  };
}

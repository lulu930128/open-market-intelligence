"use client";

import { fetchJson } from "@/lib/api";
import {
  getJpPrimaryMarketIndexConfig,
  resolveJpContextIndexConfig,
  type JPMarketIndexConfig,
} from "@/lib/jpMarketIndices";
import {
  JAPAN_INTRADAY_REFRESH_MS,
  getJapanMarketRefreshState,
  isJapanRegularSessionPoint,
} from "@/lib/jpMarketTime";
import {
  getKrPrimaryMarketIndexConfig,
  resolveKrContextIndexConfig,
  type KRMarketIndexConfig,
} from "@/lib/krMarketIndices";
import {
  getUsPrimaryMarketIndexConfig,
  resolveUsContextIndexConfig,
  type USMarketIndexConfig,
} from "@/lib/usMarketIndices";
import {
  US_INTRADAY_REFRESH_MS,
  getUsMarketRefreshState,
  isUsRegularSessionPoint,
} from "@/lib/usMarketTime";
import type {
  IntradayTrendResponse,
  JPMarketOverviewRead,
  JPStockMasterRead,
  JPOhlcChartRead,
  KRIndexOhlcChartRead,
  KRMarketBreadthRead,
  KRStockMasterRead,
  USCompanyProfileRead,
  USOhlcChartRead,
} from "@/types/market";
import { useEffect, useMemo, useRef, useState } from "react";

import type { DashboardLoadState } from "@/components/market-dashboard/dashboardFormatters";

type MarketTapeConfig = { symbol: string };
type MarketTapeSnapshot = { symbol: string; asOf: string | null };

export type USMarketTapeSnapshot = {
  symbol: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
  close: number | null;
  change: number | null;
  changePct: number | null;
  priceVsMa20: number | null;
  volume: number | null;
  pointCount: number;
  asOf: string | null;
  source: "quote" | "intraday" | "daily";
};

export type JPMarketTapeSnapshot = {
  symbol: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
  close: number | null;
  change: number | null;
  changePct: number | null;
  priceVsMa20: number | null;
  volume: number | null;
  pointCount: number;
  asOf: string | null;
  expectedTradeDate: string | null;
  freshnessStatus: string;
  isCurrent: boolean;
  source: "intraday" | "daily";
};

export type KRMarketTapeSnapshot = {
  symbol: string;
  indexId: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
  close: number | null;
  change: number | null;
  changePct: number | null;
  priceVsMa20: number | null;
  volume: number | null;
  pointCount: number;
  asOf: string | null;
  breadth: KRMarketBreadthRead | null;
};

export type RegionalMarketTapeState<Snapshot> = {
  primarySnapshot: Snapshot | null;
  contextSnapshot: Snapshot | null;
  loadState: DashboardLoadState;
  asOf: string | null;
};

function averageLastNumbers(
  values: Array<number | null | undefined>,
  windowSize: number
) {
  const validValues = values
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value);
    })
    .slice(-windowSize);

  if (!validValues.length) return null;

  return validValues.reduce((total, value) => total + value, 0) / validValues.length;
}

function sumUsIntradayVolume(points: IntradayTrendResponse["points"]) {
  const regularVolumes = points
    .filter((point) => isUsRegularSessionPoint(point.time))
    .map((point) => point.volume)
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value) && value > 0;
    });

  if (!regularVolumes.length) return null;

  return regularVolumes.reduce((total, value) => total + value, 0);
}

function sumJpIntradayVolume(points: IntradayTrendResponse["points"]) {
  const regularVolumes = points
    .filter((point) => isJapanRegularSessionPoint(point.time))
    .map((point) => point.volume)
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value) && value > 0;
    });

  if (!regularVolumes.length) return null;

  return regularVolumes.reduce((total, value) => total + value, 0);
}

async function fetchUsMarketTapeSnapshot(config: USMarketIndexConfig) {
  const [chart, intraday] = await Promise.all([
    fetchJson<USOhlcChartRead>(
      `/api/us-market/ohlc/${encodeURIComponent(config.symbol)}`,
      {
        timeframe: "daily",
        bars: 60,
        ensure_history: false,
        outputsize: "compact",
      }
    ),
    fetchJson<IntradayTrendResponse>(
      `/api/us-market/intraday/${encodeURIComponent(config.symbol)}`
    ).catch(() => null),
  ]);
  const chartPoints = chart.points ?? [];
  const latestDaily = chartPoints[chartPoints.length - 1] ?? null;
  const previousDaily = chartPoints[chartPoints.length - 2] ?? null;
  const latestIntraday = intraday?.points[intraday.points.length - 1] ?? null;
  const currentObservation = intraday?.current_observation ?? null;
  const currentPrice = currentObservation?.value ?? null;
  const close = currentPrice ?? latestIntraday?.price ?? latestDaily?.close ?? null;
  const previousClose = currentObservation
    ? currentObservation.previous_close ?? null
    : latestIntraday && intraday?.previous_close !== null && intraday?.previous_close !== undefined
      ? intraday.previous_close
      : previousDaily?.close ?? null;
  const change = close !== null && previousClose !== null ? close - previousClose : null;
  const changePct =
    change !== null && previousClose !== null && previousClose !== 0
      ? (change / previousClose) * 100
      : null;
  const ma20 = averageLastNumbers(
    chartPoints.map((point) => point.close),
    20
  );
  const priceVsMa20 =
    close !== null && ma20 !== null && ma20 !== 0
      ? ((close - ma20) / ma20) * 100
      : null;

  return {
    symbol: config.symbol,
    displaySymbol: config.displaySymbol,
    name: config.name,
    exchange: config.exchange,
    note: config.note,
    close,
    change,
    changePct,
    priceVsMa20,
    volume: latestIntraday
      ? sumUsIntradayVolume(intraday?.points ?? []) ?? latestDaily?.volume ?? null
      : latestDaily?.volume ?? null,
    pointCount: chart.point_count,
    asOf: currentObservation?.observed_at ?? latestIntraday?.time ?? latestDaily?.time ?? null,
    source:
      currentObservation?.price_semantics === "resolved_quote_last_trade"
        ? "quote"
        : currentObservation?.price_semantics === "resolved_intraday_bar_close" || latestIntraday
          ? "intraday"
          : "daily",
  } satisfies USMarketTapeSnapshot;
}

async function fetchJpMarketTapeSnapshot(config: JPMarketIndexConfig) {
  const [chart, intraday] = await Promise.all([
    fetchJson<JPOhlcChartRead>(
      `/api/jp-market/ohlc/${encodeURIComponent(config.symbol)}`,
      {
        timeframe: "daily",
        bars: 60,
        ensure_history: false,
        outputsize: "compact",
        provider: "auto",
      }
    ),
    fetchJson<IntradayTrendResponse>(
      `/api/jp-market/intraday/${encodeURIComponent(config.symbol)}`
    ).catch(() => null),
  ]);
  const chartPoints = chart.points ?? [];
  const latestDaily = chartPoints[chartPoints.length - 1] ?? null;
  const previousDaily = chartPoints[chartPoints.length - 2] ?? null;
  const latestIntraday = intraday?.points[intraday.points.length - 1] ?? null;
  const marketState = getJapanMarketRefreshState();
  const intradayTradeDate = latestIntraday?.time.slice(0, 10) ?? null;
  const expectedIntradayTradeDate =
    marketState.sessionPhase === "pre_market_pending" ||
    marketState.sessionPhase === "market_closed"
      ? chart.expected_data_date
      : marketState.dateKey;
  const intradayIsCurrent = Boolean(
    intradayTradeDate &&
      expectedIntradayTradeDate &&
      intradayTradeDate === expectedIntradayTradeDate
  );
  const close = latestIntraday?.price ?? latestDaily?.close ?? null;
  const previousClose =
    latestIntraday && intraday?.previous_close !== null && intraday?.previous_close !== undefined
      ? intraday.previous_close
      : previousDaily?.close ?? null;
  const change = close !== null && previousClose !== null ? close - previousClose : null;
  const changePct =
    change !== null && previousClose !== null && previousClose !== 0
      ? (change / previousClose) * 100
      : null;
  const ma20 = averageLastNumbers(
    chartPoints.map((point) => point.close),
    20
  );
  const priceVsMa20 =
    close !== null && ma20 !== null && ma20 !== 0
      ? ((close - ma20) / ma20) * 100
      : null;

  return {
    symbol: config.symbol,
    displaySymbol: config.displaySymbol,
    name: config.name,
    exchange: config.exchange,
    note: config.note,
    close,
    change,
    changePct,
    priceVsMa20,
    volume: latestIntraday
      ? sumJpIntradayVolume(intraday?.points ?? []) ?? latestDaily?.volume ?? null
      : latestDaily?.volume ?? null,
    pointCount: chart.point_count,
    asOf: latestIntraday?.time ?? latestDaily?.time ?? null,
    expectedTradeDate: chart.expected_data_date,
    freshnessStatus: latestIntraday
      ? intradayIsCurrent
        ? "current"
        : "stale"
      : chart.freshness_status,
    isCurrent: latestIntraday ? intradayIsCurrent : chart.is_current,
    source: latestIntraday ? "intraday" : "daily",
  } satisfies JPMarketTapeSnapshot;
}

async function fetchKrMarketTapeSnapshot(config: KRMarketIndexConfig) {
  const [chart, breadth] = await Promise.all([
    fetchJson<KRIndexOhlcChartRead>(
      `/api/kr-market/indices/${encodeURIComponent(config.indexId)}/ohlc`,
      {
        timeframe: "daily",
        bars: 60,
        ensure_history: false,
      }
    ),
    fetchJson<KRMarketBreadthRead>(
      `/api/kr-market/indices/${encodeURIComponent(config.indexId)}/breadth`
    ),
  ]);
  const chartPoints = chart.points ?? [];
  const latestDaily = chartPoints[chartPoints.length - 1] ?? null;
  const previousDaily = chartPoints[chartPoints.length - 2] ?? null;
  const close = latestDaily?.close ?? null;
  const previousClose = previousDaily?.close ?? null;
  const change = close !== null && previousClose !== null ? close - previousClose : null;
  const changePct =
    change !== null && previousClose !== null && previousClose !== 0
      ? (change / previousClose) * 100
      : null;
  const ma20 = averageLastNumbers(
    chartPoints.map((point) => point.close),
    20
  );
  const priceVsMa20 =
    close !== null && ma20 !== null && ma20 !== 0
      ? ((close - ma20) / ma20) * 100
      : null;

  return {
    symbol: config.symbol,
    indexId: config.indexId,
    displaySymbol: config.displaySymbol,
    name: config.name,
    exchange: config.exchange,
    note: config.note,
    close,
    change,
    changePct,
    priceVsMa20,
    volume: latestDaily?.volume ?? null,
    pointCount: chart.point_count,
    asOf: latestDaily?.time ?? null,
    breadth,
  } satisfies KRMarketTapeSnapshot;
}

function uniqueConfigs<Config extends MarketTapeConfig>(configs: Config[]) {
  return configs.filter((config, index, items) => {
    return items.findIndex((item) => item.symbol === config.symbol) === index;
  });
}

function latestAsOf<Snapshot extends MarketTapeSnapshot>(
  primarySnapshot: Snapshot | null,
  contextSnapshot: Snapshot | null
) {
  return (
    [primarySnapshot?.asOf, contextSnapshot?.asOf]
      .filter((value): value is string => Boolean(value))
      .sort((left, right) => left.localeCompare(right))
      .at(-1) ?? null
  );
}

function usePollingMarketTapeState<
  Config extends MarketTapeConfig,
  Snapshot extends MarketTapeSnapshot,
>({
  configs,
  primarySymbol,
  contextSymbol,
  loadSnapshot,
  refreshDelay,
  onError,
}: {
  configs: Config[];
  primarySymbol: string;
  contextSymbol: string;
  loadSnapshot: (config: Config) => Promise<Snapshot>;
  refreshDelay: () => number;
  onError: (error: unknown) => void;
}) {
  const [snapshots, setSnapshots] = useState<Record<string, Snapshot>>({});
  const [loadState, setLoadState] = useState<DashboardLoadState>("idle");
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let requestInFlight = false;

    function clearTimer() {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
    }

    async function loadSnapshots(silent = false) {
      if (requestInFlight) return;
      requestInFlight = true;

      if (!silent) {
        setLoadState("loading");
      }

      try {
        const nextSnapshots = await Promise.all(configs.map((config) => loadSnapshot(config)));

        if (cancelled) return;

        setSnapshots((current) => {
          const updated = { ...current };
          nextSnapshots.forEach((snapshot) => {
            updated[snapshot.symbol] = snapshot;
          });
          return updated;
        });
        setLoadState("success");
      } catch (error) {
        if (cancelled) return;

        setLoadState("error");
        onErrorRef.current(error);
      } finally {
        requestInFlight = false;
      }
    }

    function scheduleRefresh() {
      if (cancelled) return;

      timer = window.setTimeout(() => {
        void loadSnapshots(true).finally(scheduleRefresh);
      }, refreshDelay());
    }

    void loadSnapshots().finally(scheduleRefresh);

    return () => {
      cancelled = true;
      clearTimer();
    };
  }, [configs, loadSnapshot, refreshDelay]);

  const primarySnapshot = snapshots[primarySymbol] ?? null;
  const contextSnapshot = snapshots[contextSymbol] ?? null;

  return {
    primarySnapshot,
    contextSnapshot,
    loadState,
    asOf: latestAsOf(primarySnapshot, contextSnapshot),
  } satisfies RegionalMarketTapeState<Snapshot>;
}

function usRefreshDelay() {
  const marketState = getUsMarketRefreshState();
  return marketState.isPollingWindow
    ? US_INTRADAY_REFRESH_MS
    : Math.min(marketState.msUntilNextPollingStart, 60_000);
}

function regionalDailyRefreshDelay() {
  return 300_000;
}

function jpRefreshDelay() {
  const marketState = getJapanMarketRefreshState();
  return marketState.isPollingWindow
    ? JAPAN_INTRADAY_REFRESH_MS
    : Math.min(marketState.msUntilNextPollingStart, 300_000);
}

export function useUsMarketTapeState({
  selectedSymbol,
  selectedSecurityName,
  selectedGroupName,
  companyProfile,
  onError,
}: {
  selectedSymbol: string | null;
  selectedSecurityName: string | null;
  selectedGroupName: string | null;
  companyProfile: USCompanyProfileRead | null;
  onError: (error: unknown) => void;
}) {
  const primaryIndex = useMemo(() => getUsPrimaryMarketIndexConfig(), []);
  const contextIndex = useMemo(
    () =>
      resolveUsContextIndexConfig({
        symbol: selectedSymbol,
        securityName: selectedSecurityName,
        groupName: selectedGroupName,
        profile: companyProfile,
      }),
    [companyProfile, selectedGroupName, selectedSecurityName, selectedSymbol]
  );
  const configs = useMemo(
    () => uniqueConfigs([primaryIndex, contextIndex]),
    [contextIndex, primaryIndex]
  );

  return usePollingMarketTapeState({
    configs,
    primarySymbol: primaryIndex.symbol,
    contextSymbol: contextIndex.symbol,
    loadSnapshot: fetchUsMarketTapeSnapshot,
    refreshDelay: usRefreshDelay,
    onError,
  });
}

export function useJpMarketTapeState({
  selectedSymbol,
  selectedStock,
  selectedGroupName,
  onError,
}: {
  selectedSymbol: string | null;
  selectedStock: JPStockMasterRead | null;
  selectedGroupName: string | null;
  onError: (error: unknown) => void;
}) {
  const primaryIndex = useMemo(() => getJpPrimaryMarketIndexConfig(), []);
  const contextIndex = useMemo(
    () =>
      resolveJpContextIndexConfig({
        symbol: selectedSymbol,
        securityName: selectedStock?.security_name ?? null,
        groupName: selectedGroupName,
        stock: selectedStock,
      }),
    [selectedGroupName, selectedStock, selectedSymbol]
  );
  const configs = useMemo(
    () => uniqueConfigs([primaryIndex, contextIndex]),
    [contextIndex, primaryIndex]
  );
  const tapeState = usePollingMarketTapeState({
    configs,
    primarySymbol: primaryIndex.symbol,
    contextSymbol: contextIndex.symbol,
    loadSnapshot: fetchJpMarketTapeSnapshot,
    refreshDelay: jpRefreshDelay,
    onError,
  });
  const [overview, setOverview] = useState<JPMarketOverviewRead | null>(null);
  const [overviewLoadState, setOverviewLoadState] = useState<DashboardLoadState>("idle");
  const overviewErrorRef = useRef(onError);

  useEffect(() => {
    overviewErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function loadOverview(silent = false) {
      if (!silent) setOverviewLoadState("loading");
      try {
        const payload = await fetchJson<JPMarketOverviewRead>("/api/jp-market/overview", {
          sector_limit: 10,
          mover_limit: 5,
        });
        if (cancelled) return;
        setOverview(payload);
        setOverviewLoadState("success");
      } catch (error) {
        if (cancelled) return;
        setOverviewLoadState("error");
        overviewErrorRef.current(error);
      }
    }

    function scheduleRefresh() {
      if (cancelled) return;
      timer = window.setTimeout(() => {
        void loadOverview(true).finally(scheduleRefresh);
      }, regionalDailyRefreshDelay());
    }

    void loadOverview().finally(scheduleRefresh);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  return {
    ...tapeState,
    overview,
    overviewLoadState,
  };
}

export function useKrMarketTapeState({
  selectedSymbol,
  selectedStock,
  selectedGroupName,
  onError,
}: {
  selectedSymbol: string | null;
  selectedStock: KRStockMasterRead | null;
  selectedGroupName: string | null;
  onError: (error: unknown) => void;
}) {
  const primaryIndex = useMemo(() => getKrPrimaryMarketIndexConfig(), []);
  const contextIndex = useMemo(
    () =>
      resolveKrContextIndexConfig({
        symbol: selectedSymbol,
        securityName:
          selectedStock?.security_name ?? selectedStock?.security_name_kr ?? null,
        groupName: selectedGroupName,
        stock: selectedStock,
      }),
    [selectedGroupName, selectedStock, selectedSymbol]
  );
  const configs = useMemo(
    () => uniqueConfigs([primaryIndex, contextIndex]),
    [contextIndex, primaryIndex]
  );

  return usePollingMarketTapeState({
    configs,
    primarySymbol: primaryIndex.symbol,
    contextSymbol: contextIndex.symbol,
    loadSnapshot: fetchKrMarketTapeSnapshot,
    refreshDelay: regionalDailyRefreshDelay,
    onError,
  });
}

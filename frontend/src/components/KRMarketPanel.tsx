"use client";

import IntradayTrendChart, {
  defaultIntradayIndicators,
  type IntradayIndicatorSettings,
  type IntradaySessionConfig,
} from "@/components/IntradayTrendChart";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import ResourceSlotTabs from "@/components/market-detail/ResourceSlotTabs";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import type { ResourceSlotTabItem } from "@/components/market-detail/types";
import { timeframeLabel, useT } from "@/i18n";
import { fetchJson, requestJson } from "@/lib/api";
import { getKrMarketIndexConfig } from "@/lib/krMarketIndices";
import {
  KOREA_INTRADAY_REFRESH_MS,
  KOREA_SESSION_END_MINUTES,
  KOREA_SESSION_START_MINUTES,
  getKoreaIntradayXRatio,
  getKoreaMarketRefreshState,
  getSeoulMinutesOfDay,
  isKoreaRegularSessionPoint,
} from "@/lib/krMarketTime";
import type {
  ChartPoint,
  IntradayTrendPoint,
  IntradayTrendResponse,
  KRCompanyFundamentalRead,
  KRDailyPriceRefreshResultRead,
  KRIndexOhlcChartRead,
  KRIndexRefreshResultRead,
  KRInvestorTradeDailyRead,
  KRMarketBreadthRead,
  KRMarketBreadthRefreshResultRead,
  KROhlcChartRead,
  KROhlcPointRead,
  KRResourceRefreshResultRead,
  KRResourceSlotRead,
  KRResourceSummaryRead,
  KRSourceHealthRead,
  KRStockMasterRead,
  KRStockMasterSyncResultRead,
  KRWatchlistReadinessRead,
} from "@/types/market";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type Message = { type: "success" | "warning" | "error"; text: string } | null;
type KRHistoricalTimeframe = "daily" | "weekly" | "monthly";
type KRChartTimeframe = "today" | KRHistoricalTimeframe;
type KRChartRead = KROhlcChartRead | KRIndexOhlcChartRead;
type KRDataSlot = "demand" | "investors" | "disclosures" | "performance" | "financials";

type Props = {
  initialSymbol: string | null;
  selectedGroupId?: number | null;
  refreshNonce?: number;
  watchlistRankingPanel?: ReactNode;
  onSelectStock: (stock: KRStockMasterRead | null) => void;
  onStatusMessage?: (message: Message) => void;
};

const indexTimeframeOptions: KRChartTimeframe[] = ["today", "daily", "weekly", "monthly"];
const stockTimeframeOptions: KRHistoricalTimeframe[] = ["daily", "weekly", "monthly"];
const barsByTimeframe: Record<KRHistoricalTimeframe, number> = {
  daily: 180,
  weekly: 104,
  monthly: 72,
};
const krDataSlots: Array<{ key: KRDataSlot; resourceKey: string; titleKey: string; descriptionKey: string }> = [
  {
    key: "demand",
    resourceKey: "daily_price",
    titleKey: "krMarket.dataSlots.demand.title",
    descriptionKey: "krMarket.dataSlots.demand.description",
  },
  {
    key: "investors",
    resourceKey: "investor_trading",
    titleKey: "krMarket.dataSlots.investors.title",
    descriptionKey: "krMarket.dataSlots.investors.description",
  },
  {
    key: "disclosures",
    resourceKey: "disclosures",
    titleKey: "krMarket.dataSlots.disclosures.title",
    descriptionKey: "krMarket.dataSlots.disclosures.description",
  },
  {
    key: "performance",
    resourceKey: "financials",
    titleKey: "krMarket.dataSlots.performance.title",
    descriptionKey: "krMarket.dataSlots.performance.description",
  },
  {
    key: "financials",
    resourceKey: "financials",
    titleKey: "krMarket.dataSlots.financials.title",
    descriptionKey: "krMarket.dataSlots.financials.description",
  },
];

const krChartIndicators: IndicatorSettings = {
  ...defaultIndicators,
  ma: true,
  volume: true,
  signals: false,
};

const krIndexIntradaySession: IntradaySessionConfig = {
  startMinutes: KOREA_SESSION_START_MINUTES,
  endMinutes: KOREA_SESSION_END_MINUTES,
  timeTicks: [
    { label: "09:00", minutes: 9 * 60 },
    { label: "10:30", minutes: 10 * 60 + 30 },
    { label: "12:00", minutes: 12 * 60 },
    { label: "13:30", minutes: 13 * 60 + 30 },
    { label: "15:00", minutes: 15 * 60 },
    { label: "15:30", minutes: 15 * 60 + 30 },
  ],
  getMinutesOfDay: getSeoulMinutesOfDay,
  getXRatio: getKoreaIntradayXRatio,
  isRegularSessionPoint: isKoreaRegularSessionPoint,
  volumeFormatter: formatWholeNumber,
};

function normalizeSymbolInput(value: string) {
  const input = value.trim().toUpperCase();
  if (!input) return "";

  const token = input.includes(":") ? input.split(":").pop()?.trim() ?? input : input;
  return token.replace(/\s+/g, "");
}

function apiErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function isRefreshSuccess(status: string | null | undefined) {
  return status === "success" || status === "partial_success";
}

function formatNumber(value: number | null | undefined, maximumFractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("en-US", { maximumFractionDigits });
}

function formatWholeNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function formatCompactMoney(value: number | null | undefined, currency: string | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const prefix = currency ? `${currency} ` : "";
  const absValue = Math.abs(value);
  if (absValue >= 1_000_000_000_000) return `${prefix}${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (absValue >= 1_000_000_000) return `${prefix}${(value / 1_000_000_000).toFixed(2)}B`;
  if (absValue >= 1_000_000) return `${prefix}${(value / 1_000_000).toFixed(2)}M`;
  return `${prefix}${formatWholeNumber(value)}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function formatKoreaDateTime(value: string | null | undefined) {
  if (!value) return "-";

  const date = new Date(value);
  if (Number.isNaN(date.getTime()) || !value.includes("T")) return value;

  return new Intl.DateTimeFormat("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul",
  }).format(date);
}

function formatSignedNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, 2)}`;
}

function formatSignedPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${formatSignedNumber(value)}%`;
}

function formatRatioPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(0)}%`;
}

function priceToneClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "text-omi-text-muted";
  if (value > 0) return "text-omi-danger";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text-muted";
}

function resourceStatusClass(status: string | null | undefined) {
  if (status === "available") return "text-omi-market-down";
  if (status === "empty" || status === "stale") return "text-omi-warning";
  if (status === "error") return "text-omi-danger";
  if (status === "loading") return "text-omi-accent";
  return "text-omi-text-muted";
}

function resourceStatusLabelKey(status: string | null | undefined) {
  if (status === "available") return "krMarket.dataSlots.statusLabels.available";
  if (status === "empty") return "krMarket.dataSlots.statusLabels.empty";
  if (status === "error") return "krMarket.dataSlots.statusLabels.error";
  if (status === "stale") return "krMarket.dataSlots.statusLabels.stale";
  if (status === "loading") return "krMarket.dataSlots.statusLabels.loading";
  return "krMarket.dataSlots.statusLabels.planned";
}

function readinessStatusClass(status: string | null | undefined) {
  if (status === "ready" || status === "current") {
    return "border-omi-success-border bg-omi-success-soft text-omi-success";
  }
  if (status === "partial" || status === "stale") {
    return "border-omi-warning-border bg-omi-warning-soft text-omi-warning";
  }
  if (status === "loading") {
    return "border-omi-info-border bg-omi-info-soft text-omi-info";
  }
  if (status === "error") {
    return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  }
  return "border-omi-border-subtle bg-omi-surface-subtle text-omi-text-muted";
}

function readinessStatusLabelKey(status: string | null | undefined) {
  if (status === "ready") return "krMarket.readiness.status.ready";
  if (status === "current") return "krMarket.readiness.status.current";
  if (status === "partial") return "krMarket.readiness.status.partial";
  if (status === "stale") return "krMarket.readiness.status.stale";
  if (status === "loading") return "krMarket.readiness.status.loading";
  if (status === "error") return "krMarket.readiness.status.error";
  if (status === "missing") return "krMarket.readiness.status.missing";
  return "krMarket.readiness.status.empty";
}

function messageToneClass(type: "success" | "warning" | "error") {
  if (type === "success") return "border-omi-success-border bg-omi-success-soft text-omi-success";
  if (type === "warning") return "border-omi-warning-border bg-omi-warning-soft text-omi-warning";
  return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
}

function readinessResourceLabelKey(resource: string) {
  if (resource === "daily_price") return "krMarket.readiness.resources.dailyPrice";
  if (resource === "investor_trading") return "krMarket.readiness.resources.investorTrading";
  if (resource === "financials") return "krMarket.readiness.resources.financials";
  return "krMarket.readiness.resources.other";
}

function toChartPoint(point: KROhlcPointRead): ChartPoint {
  return {
    time: point.time,
    open: point.open,
    high: point.high,
    low: point.low,
    close: point.close,
    volume: point.volume,
    trade_value: null,
    transaction_count: null,
  };
}

async function fetchKrIndexIntradayTrend(indexId: string, refresh = false) {
  return fetchJson<IntradayTrendResponse>(
    `/api/kr-market/indices/${encodeURIComponent(indexId)}/intraday`,
    refresh ? { refresh: true } : undefined
  );
}

function latestPoint(points: ChartPoint[]) {
  return points.length > 0 ? points[points.length - 1] : null;
}

function previousPoint(points: ChartPoint[]) {
  return points.length > 1 ? points[points.length - 2] : null;
}

function changeValue(points: ChartPoint[]) {
  const latest = latestPoint(points);
  const previous = previousPoint(points);
  if (latest?.close === null || latest?.close === undefined) return null;
  if (previous?.close === null || previous?.close === undefined) return null;
  return latest.close - previous.close;
}

function changePct(points: ChartPoint[]) {
  const previous = previousPoint(points);
  const change = changeValue(points);
  if (change === null) return null;
  if (previous?.close === null || previous?.close === undefined || previous.close === 0) return null;
  return (change / previous.close) * 100;
}

function movingAverage(points: ChartPoint[], key: "close" | "volume", windowSize: number) {
  const values = points
    .slice(-windowSize)
    .map((point) => point[key])
    .filter((value): value is number => value !== null && value !== undefined);
  if (values.length < 1) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3">
      <div className="text-xs font-semibold text-omi-text-muted">{label}</div>
      <div className="mt-1 truncate text-lg font-bold text-omi-text-strong">{value}</div>
    </div>
  );
}

function ReadinessCell({
  label,
  status,
  detail,
}: {
  label: string;
  status: string;
  detail: string;
}) {
  return (
    <div className={`border px-2.5 py-2 ${readinessStatusClass(status)}`}>
      <div className="text-[11px] font-black uppercase tracking-[0.12em] opacity-80">{label}</div>
      <div className="mt-1 truncate text-sm font-black">{detail}</div>
    </div>
  );
}

export default function KRMarketPanel({
  initialSymbol,
  selectedGroupId = null,
  refreshNonce = 0,
  watchlistRankingPanel,
  onSelectStock,
  onStatusMessage,
}: Props) {
  const t = useT();
  const onSelectStockRef = useRef(onSelectStock);
  const [selectedStock, setSelectedStock] = useState<KRStockMasterRead | null>(null);
  const [chart, setChart] = useState<KRChartRead | null>(null);
  const [resourceSummary, setResourceSummary] = useState<KRResourceSummaryRead | null>(null);
  const [indexBreadth, setIndexBreadth] = useState<KRMarketBreadthRead | null>(null);
  const [indexBreadthMessage, setIndexBreadthMessage] = useState<Message>(null);
  const [fundamentals, setFundamentals] = useState<KRCompanyFundamentalRead[]>([]);
  const [investorRows, setInvestorRows] = useState<KRInvestorTradeDailyRead[]>([]);
  const [sourceHealth, setSourceHealth] = useState<KRSourceHealthRead | null>(null);
  const [watchlistReadiness, setWatchlistReadiness] = useState<KRWatchlistReadinessRead | null>(null);
  const [timeframe, setTimeframe] = useState<KRChartTimeframe>("daily");
  const [activeDataSlot, setActiveDataSlot] = useState<KRDataSlot>("demand");
  const [stockState, setStockState] = useState<LoadState>("idle");
  const [dataState, setDataState] = useState<LoadState>("idle");
  const [readinessState, setReadinessState] = useState<LoadState>("idle");
  const [refreshing, setRefreshing] = useState(false);
  const [chartIndicators] = useState<IndicatorSettings>(krChartIndicators);
  const [intradayIndicators] = useState<IntradayIndicatorSettings>(defaultIntradayIndicators);
  const [todayTrend, setTodayTrend] = useState<IntradayTrendPoint[]>([]);
  const [todayPreviousClose, setTodayPreviousClose] = useState<number | null>(null);
  const [todaySource, setTodaySource] = useState("naver_index_time");
  const [todayUpdatedAt, setTodayUpdatedAt] = useState<string | null>(null);
  const [todayIntradayState, setTodayIntradayState] = useState<LoadState>("idle");
  const [todayIntradayMessage, setTodayIntradayMessage] = useState<Message>(null);
  const finalIntradayRefreshDate = useRef<string | null>(null);

  const chartData = useMemo<ChartPoint[]>(
    () => chart?.points.map(toChartPoint) ?? [],
    [chart]
  );
  const latest = latestPoint(chartData);
  const change = changeValue(chartData);
  const pct = changePct(chartData);
  const todayLatest = todayTrend[todayTrend.length - 1] ?? null;
  const ma20 = useMemo(() => movingAverage(chartData, "close", 20), [chartData]);
  const volumeMa20 = useMemo(() => movingAverage(chartData, "volume", 20), [chartData]);
  const priceVsMa20 =
    latest?.close !== null &&
    latest?.close !== undefined &&
    ma20 !== null &&
    ma20 !== 0
      ? ((latest.close - ma20) / ma20) * 100
      : null;
  const volumeVsMa20 =
    latest?.volume !== null &&
    latest?.volume !== undefined &&
    volumeMa20 !== null &&
    volumeMa20 !== 0
      ? ((latest.volume - volumeMa20) / volumeMa20) * 100
      : null;
  const selectedIndexConfig = getKrMarketIndexConfig(selectedStock?.symbol ?? initialSymbol);
  const isSelectedIndex = selectedIndexConfig !== null;
  const selectedIndexId = selectedIndexConfig?.indexId ?? null;
  const timeframeOptions = isSelectedIndex ? indexTimeframeOptions : stockTimeframeOptions;
  const isIntradayTimeframe = isSelectedIndex && timeframe === "today";
  const displayPrice =
    isIntradayTimeframe && todayLatest ? todayLatest.price : latest?.close ?? null;
  const displayChange =
    isIntradayTimeframe && todayLatest && todayPreviousClose !== null
      ? todayLatest.price - todayPreviousClose
      : change;
  const displayPct =
    isIntradayTimeframe &&
    todayLatest &&
    todayPreviousClose !== null &&
    todayPreviousClose !== 0
      ? ((todayLatest.price - todayPreviousClose) / todayPreviousClose) * 100
      : pct;
  const todayChartLoading = todayIntradayState === "loading" && todayTrend.length < 2;
  const selectedTitle = selectedIndexConfig
    ? `${selectedIndexConfig.displaySymbol} ${selectedIndexConfig.name}`.trim()
    : selectedStock
      ? `${selectedStock.symbol} ${selectedStock.security_name ?? selectedStock.security_name_kr ?? ""}`.trim()
    : t("krMarket.empty.noStockSelected");
  const selectedSubtitle = selectedIndexConfig
    ? [
        selectedIndexConfig.exchange,
        t("krMarket.entity.index"),
        selectedIndexConfig.marketSegment,
        selectedIndexConfig.note,
      ]
        .filter(Boolean)
        .join(" / ")
    : selectedStock
      ? [
          selectedStock.exchange ?? "KRX",
          selectedStock.market_segment,
          selectedStock.sector,
          selectedStock.industry,
          selectedStock.asset_type,
        ]
          .filter(Boolean)
          .join(" / ")
      : t("krMarket.empty.selectStockPrompt");
  const chartLoading = stockState === "loading" || dataState === "loading";

  const latestFundamental = fundamentals[0] ?? null;
  const latestInvestorRows = useMemo(() => {
    const latestDate = investorRows[0]?.trade_date ?? null;
    return latestDate
      ? investorRows.filter((row) => row.trade_date === latestDate)
      : [];
  }, [investorRows]);
  const investorByType = useMemo(() => {
    const map = new Map<string, KRInvestorTradeDailyRead>();
    latestInvestorRows.forEach((row) => map.set(row.investor_type.toLowerCase(), row));
    return map;
  }, [latestInvestorRows]);

  const resourceSlotLabels = useMemo(
    () => ({
      eyebrow: t("krMarket.sections.marketData"),
      status: t("krMarket.dataSlots.status"),
      source: t("krMarket.dataSlots.source"),
      latestDate: t("krMarket.dataSlots.latestDate"),
      rows: t("krMarket.dataSlots.rows"),
      reserved: t("krMarket.dataSlots.reserved"),
    }),
    [t]
  );
  const resourceSlotItems = useMemo<Array<ResourceSlotTabItem<KRDataSlot>>>(
    () =>
      krDataSlots.map((slot) => {
        const resourceSlot =
          resourceSummary?.slots.find((item) => item.key === slot.resourceKey) ?? null;
        const status =
          dataState === "loading" ? "loading" : resourceSlot?.status ?? "planned";

        return {
          key: slot.key,
          label: t(`krMarket.dataSlots.${slot.key}.label`),
          title: t(slot.titleKey),
          description: t(slot.descriptionKey),
          status,
          source: resourceSlot?.source ?? t("krMarket.dataSlots.planned"),
          latestDate: resourceSlot?.latest_date ? formatDate(resourceSlot.latest_date) : "-",
          rowCount: resourceSlot === null ? "-" : formatWholeNumber(resourceSlot.row_count),
        };
      }),
    [dataState, resourceSummary, t]
  );
  const activeResourceSlot = useMemo<KRResourceSlotRead | null>(() => {
    const activeSlot = krDataSlots.find((slot) => slot.key === activeDataSlot);
    if (!activeSlot) return null;
    return resourceSummary?.slots.find((item) => item.key === activeSlot.resourceKey) ?? null;
  }, [activeDataSlot, resourceSummary]);
  const activeSlotDetail = useMemo(
    () => ({
      eyebrow: t("krMarket.slotDetails.eyebrow"),
      title: t(`krMarket.slotDetails.${activeDataSlot}.title`),
      subtitle:
        activeResourceSlot?.available || fundamentals.length || investorRows.length
          ? `${activeResourceSlot?.source ?? "-"} · ${formatDate(activeResourceSlot?.latest_date)}`
          : t(`krMarket.slotDetails.${activeDataSlot}.empty`),
    }),
    [activeDataSlot, activeResourceSlot, fundamentals.length, investorRows.length, t]
  );
  const activeSlotMetrics = useMemo(() => {
    const metricNumber = (key: string) => {
      const value = activeResourceSlot?.metrics?.[key];
      return typeof value === "number" && Number.isFinite(value) ? value : null;
    };
    const latestInvestor = latestInvestorRows[0] ?? null;
    const foreignRow =
      investorByType.get("foreign") ??
      investorByType.get("foreigners") ??
      investorByType.get("foreigner") ??
      null;
    const institutionRow =
      investorByType.get("institution") ??
      investorByType.get("institutions") ??
      investorByType.get("institutional") ??
      null;
    const individualRow =
      investorByType.get("individual") ??
      investorByType.get("individuals") ??
      null;

    if (activeDataSlot === "demand") {
      return [
        { label: t("krMarket.slotMetrics.latestDate"), value: formatDate(activeResourceSlot?.latest_date) },
        { label: t("krMarket.slotMetrics.close"), value: formatNumber(metricNumber("close_price"), 2) },
        { label: t("krMarket.metrics.volume"), value: formatWholeNumber(metricNumber("trade_volume")) },
        { label: t("krMarket.slotMetrics.marketCap"), value: formatCompactMoney(metricNumber("market_cap"), selectedStock?.currency) },
      ];
    }

    if (activeDataSlot === "investors") {
      return [
        { label: t("krMarket.slotMetrics.latestDate"), value: formatDate(latestInvestor?.trade_date) },
        { label: t("krMarket.slotMetrics.foreignNetBuy"), value: formatCompactMoney(foreignRow?.net_buy_value, selectedStock?.currency) },
        { label: t("krMarket.slotMetrics.institutionNetBuy"), value: formatCompactMoney(institutionRow?.net_buy_value, selectedStock?.currency) },
        { label: t("krMarket.slotMetrics.individualNetBuy"), value: formatCompactMoney(individualRow?.net_buy_value, selectedStock?.currency) },
      ];
    }

    if (activeDataSlot === "performance" || activeDataSlot === "financials") {
      return [
        { label: t("krMarket.slotMetrics.reportName"), value: latestFundamental?.report_name ?? "-" },
        { label: t("krMarket.slotMetrics.statementName"), value: latestFundamental?.statement_name ?? "-" },
        { label: t("krMarket.slotMetrics.accountName"), value: latestFundamental?.account_name ?? "-" },
        { label: t("krMarket.slotMetrics.currentAmount"), value: formatCompactMoney(latestFundamental?.current_amount, latestFundamental?.currency ?? selectedStock?.currency) },
        { label: t("krMarket.slotMetrics.previousAmount"), value: formatCompactMoney(latestFundamental?.previous_amount, latestFundamental?.currency ?? selectedStock?.currency) },
        { label: t("krMarket.slotMetrics.fetchedAt"), value: formatDate(latestFundamental?.fetched_at) },
      ];
    }

    return [
      { label: t("krMarket.slotMetrics.latestDisclosure"), value: "-" },
      { label: t("krMarket.slotMetrics.corpCode"), value: latestFundamental?.corp_code ?? "-" },
      { label: t("krMarket.slotMetrics.stockCode"), value: latestFundamental?.stock_code ?? "-" },
      { label: t("krMarket.slotMetrics.fetchedAt"), value: formatDate(latestFundamental?.fetched_at) },
    ];
  }, [
    activeDataSlot,
    activeResourceSlot,
    investorByType,
    latestFundamental,
    latestInvestorRows,
    selectedStock?.currency,
    t,
  ]);
  const headerMetrics = useMemo(
    () => [
      { label: t("krMarket.metrics.date"), value: formatDate(latest?.time) },
      { label: t("krMarket.metrics.close"), value: formatNumber(latest?.close, 2) },
      { label: t("krMarket.metrics.volume"), value: formatWholeNumber(latest?.volume) },
      { label: t("krMarket.metrics.segment"), value: selectedStock?.market_segment ?? "-" },
      { label: t("krMarket.metrics.sector"), value: selectedStock?.sector ?? "-" },
      { label: t("krMarket.metrics.source"), value: chart?.backfill?.provider ? String(chart.backfill.provider) : "-" },
    ],
    [chart, latest?.close, latest?.time, latest?.volume, selectedStock, t]
  );
  const technicalRows = useMemo(
    () => [
      {
        label: t("krMarket.technical.priceVsMa20"),
        value: formatSignedPct(priceVsMa20),
        tone: priceVsMa20,
        detail: ma20 === null ? t("common.noData") : `MA20 ${formatNumber(ma20, 2)}`,
      },
      {
        label: t("krMarket.technical.volumeVsMa20"),
        value: formatSignedPct(volumeVsMa20),
        tone: volumeVsMa20,
        detail:
          volumeMa20 === null
            ? t("common.noData")
            : `${t("krMarket.technical.volumeMa20")} ${formatWholeNumber(volumeMa20)}`,
      },
    ],
    [ma20, priceVsMa20, t, volumeMa20, volumeVsMa20]
  );
  const indexBreadthRows = useMemo(
    () => [
      { label: t("krMarket.metrics.date"), value: formatDate(indexBreadth?.trade_date) },
      { label: t("krMarket.metrics.advance"), value: formatWholeNumber(indexBreadth?.advance_count) },
      { label: t("krMarket.metrics.decline"), value: formatWholeNumber(indexBreadth?.decline_count) },
      { label: t("krMarket.metrics.unchanged"), value: formatWholeNumber(indexBreadth?.unchanged_count) },
      { label: t("krMarket.metrics.total"), value: formatWholeNumber(indexBreadth?.total_count) },
      { label: t("krMarket.metrics.positiveRatio"), value: formatRatioPct(indexBreadth?.positive_ratio) },
      { label: t("krMarket.metrics.averageChange"), value: formatSignedPct(indexBreadth?.average_change_pct) },
      { label: t("krMarket.metrics.tradeValue"), value: formatCompactMoney(indexBreadth?.trade_value, "KRW") },
    ],
    [indexBreadth, t]
  );
  const selectedReadiness = useMemo(() => {
    if (!selectedStock || !watchlistReadiness) return null;
    return watchlistReadiness.results.find((row) => row.symbol === selectedStock.symbol) ?? null;
  }, [selectedStock, watchlistReadiness]);
  const readinessSummaryCards = useMemo(() => {
    const summary = watchlistReadiness?.summary;

    return [
      { label: t("krMarket.readiness.summary.ready"), value: formatWholeNumber(summary?.ready_count) },
      { label: t("krMarket.readiness.summary.partial"), value: formatWholeNumber(summary?.partial_count) },
      { label: t("krMarket.readiness.summary.noData"), value: formatWholeNumber(summary?.no_data_count) },
      { label: t("krMarket.readiness.summary.investors"), value: formatWholeNumber(summary?.investor_available_count) },
    ];
  }, [t, watchlistReadiness]);
  const selectedReadinessCells = useMemo(() => {
    if (!selectedReadiness) return [];
    const investorStatus = selectedReadiness.investor_row_count > 0 ? "ready" : "missing";
    const fundamentalStatus = selectedReadiness.fundamental_row_count > 0 ? "ready" : "missing";

    return [
      {
        label: t("krMarket.readiness.labels.daily"),
        status: selectedReadiness.daily_status,
        detail: `${t(readinessStatusLabelKey(selectedReadiness.daily_status))} · ${formatDate(selectedReadiness.latest_daily_date)} · ${formatWholeNumber(selectedReadiness.daily_row_count)}`,
      },
      {
        label: t("krMarket.readiness.labels.investors"),
        status: investorStatus,
        detail: `${t(readinessStatusLabelKey(investorStatus))} · ${formatDate(selectedReadiness.latest_investor_date)} · ${formatWholeNumber(selectedReadiness.investor_row_count)}`,
      },
      {
        label: t("krMarket.readiness.labels.fundamentals"),
        status: fundamentalStatus,
        detail: `${t(readinessStatusLabelKey(fundamentalStatus))} · ${formatDate(selectedReadiness.latest_fundamental_date)} · ${formatWholeNumber(selectedReadiness.fundamental_row_count)}`,
      },
    ];
  }, [selectedReadiness, t]);
  const selectedReadinessMissingText = useMemo(() => {
    if (!selectedReadiness) return t("krMarket.readiness.unavailable");
    if (!selectedReadiness.missing_resources.length) return t("krMarket.readiness.noMissingResources");

    return t("krMarket.readiness.missingResources", {
      resources: selectedReadiness.missing_resources
        .map((resource) => t(readinessResourceLabelKey(resource)))
        .join(", "),
    });
  }, [selectedReadiness, t]);
  const readinessBadge = useMemo(() => {
    if (readinessState === "loading") return t("krMarket.readiness.loading");
    if (!watchlistReadiness) return t("krMarket.readiness.unavailable");

    return t("krMarket.readiness.groupSummary", {
      ready: watchlistReadiness.summary.ready_count,
      total: watchlistReadiness.summary.requested_symbol_count,
      partial: watchlistReadiness.summary.partial_count,
    });
  }, [readinessState, t, watchlistReadiness]);

  const publishStatus = useCallback(
    (message: Message) => {
      onStatusMessage?.(message);
    },
    [onStatusMessage]
  );

  const applyTodayTrend = useCallback((today: IntradayTrendResponse) => {
    const latestIntradayPoint = today.points[today.points.length - 1] ?? null;

    setTodayTrend(today.points);
    setTodayPreviousClose(today.previous_close);
    setTodaySource(today.source);
    setTodayUpdatedAt(latestIntradayPoint ? formatKoreaDateTime(latestIntradayPoint.time) : null);
    setTodayIntradayState("success");
    setTodayIntradayMessage(
      today.warnings?.length ? { type: "warning", text: today.warnings[0] } : null
    );
  }, []);

  useEffect(() => {
    onSelectStockRef.current = onSelectStock;
  }, [onSelectStock]);

  useEffect(() => {
    if (!isSelectedIndex && timeframe === "today") {
      const resetTimer = window.setTimeout(() => setTimeframe("daily"), 0);
      return () => window.clearTimeout(resetTimer);
    }
  }, [isSelectedIndex, timeframe]);

  const loadStockData = useCallback(
    async (symbol: string, nextTimeframe: KRChartTimeframe) => {
      setDataState("loading");

      try {
        const indexConfig = getKrMarketIndexConfig(symbol);
        const isIndexSymbol = indexConfig !== null;
        const historicalTimeframe: KRHistoricalTimeframe =
          nextTimeframe === "today" ? "daily" : nextTimeframe;
        const [
          chartResult,
          resourceResult,
          fundamentalsResult,
          investorsResult,
          sourceHealthResult,
          indexBreadthResult,
        ] = await Promise.allSettled([
          fetchJson<KRChartRead>(
            isIndexSymbol
              ? `/api/kr-market/indices/${encodeURIComponent(indexConfig.indexId)}/ohlc`
              : `/api/kr-market/ohlc/${encodeURIComponent(symbol)}`,
            {
              timeframe: historicalTimeframe,
              bars: barsByTimeframe[historicalTimeframe],
              ensure_history: false,
            }
          ),
          isIndexSymbol
            ? Promise.resolve<KRResourceSummaryRead | null>(null)
            : fetchJson<KRResourceSummaryRead>(
                `/api/kr-market/resources/${encodeURIComponent(symbol)}/summary`
              ),
          isIndexSymbol
            ? Promise.resolve<KRCompanyFundamentalRead[]>([])
            : fetchJson<KRCompanyFundamentalRead[]>("/api/kr-market/fundamentals", {
                symbol,
                limit: 20,
                offset: 0,
              }),
          isIndexSymbol
            ? Promise.resolve<KRInvestorTradeDailyRead[]>([])
            : fetchJson<KRInvestorTradeDailyRead[]>(
                `/api/kr-market/investors/${encodeURIComponent(symbol)}/history`,
                { limit: 40, offset: 0 }
              ),
          isIndexSymbol
            ? Promise.resolve<KRSourceHealthRead | null>(null)
            : fetchJson<KRSourceHealthRead>("/api/kr-market/source-health", { symbol }),
          isIndexSymbol
            ? fetchJson<KRMarketBreadthRead>(
                `/api/kr-market/indices/${encodeURIComponent(indexConfig.indexId)}/breadth`
              )
            : Promise.resolve<KRMarketBreadthRead | null>(null),
        ]);

        if (chartResult.status === "rejected") {
          throw chartResult.reason;
        }

        setChart(chartResult.value);
        setResourceSummary(resourceResult.status === "fulfilled" ? resourceResult.value : null);
        setFundamentals(fundamentalsResult.status === "fulfilled" ? fundamentalsResult.value : []);
        setInvestorRows(investorsResult.status === "fulfilled" ? investorsResult.value : []);
        setSourceHealth(sourceHealthResult.status === "fulfilled" ? sourceHealthResult.value : null);
        setIndexBreadth(indexBreadthResult.status === "fulfilled" ? indexBreadthResult.value : null);
        setDataState("success");
      } catch (error) {
        setChart(null);
        setResourceSummary(null);
        setIndexBreadth(null);
        setFundamentals([]);
        setInvestorRows([]);
        setSourceHealth(null);
        setDataState("error");
        publishStatus({
          type: "error",
          text: apiErrorMessage(error, t("krMarket.errors.dataLoadFailed")),
        });
      }
    },
    [publishStatus, t]
  );

  const loadReadiness = useCallback(async () => {
    setReadinessState("loading");

    try {
      const params = selectedGroupId === null ? undefined : { group_id: selectedGroupId };
      const result = await fetchJson<KRWatchlistReadinessRead>(
        "/api/kr-market/watchlists/readiness",
        params
      );
      setWatchlistReadiness(result);
      setReadinessState("success");
    } catch {
      setWatchlistReadiness(null);
      setReadinessState("error");
    }
  }, [selectedGroupId]);

  const loadStockBySymbol = useCallback(
    async (symbol: string, nextTimeframe: KRChartTimeframe) => {
      const normalizedSymbol = normalizeSymbolInput(symbol);
      if (!normalizedSymbol) return;

      setStockState("loading");
      publishStatus(null);
      setIndexBreadthMessage(null);

      try {
        let stock: KRStockMasterRead;

        try {
          stock = await fetchJson<KRStockMasterRead>(
            `/api/kr-market/stocks/${encodeURIComponent(normalizedSymbol)}`
          );
        } catch (error) {
          const indexConfig = getKrMarketIndexConfig(normalizedSymbol);
          if (!indexConfig) {
            throw error;
          }

          stock = {
            id: 0,
            symbol: indexConfig.symbol,
            local_code: indexConfig.indexId,
            security_name: indexConfig.name,
            security_name_kr: indexConfig.nameKr,
            exchange: indexConfig.exchange,
            market_segment: indexConfig.marketSegment,
            sector: null,
            industry: null,
            asset_type: "index",
            listing_source: "market_index_config",
            currency: "KRW",
            exchange_timezone_name: "Asia/Seoul",
            is_active: true,
            first_seen_at: "",
            last_seen_at: "",
            created_at: "",
            updated_at: "",
          };
        }
        setSelectedStock(stock);
        setStockState("success");
        onSelectStockRef.current(stock);
        await loadStockData(stock.symbol, nextTimeframe);
      } catch (error) {
        setSelectedStock(null);
        setChart(null);
        setResourceSummary(null);
        setIndexBreadth(null);
        setIndexBreadthMessage(null);
        setFundamentals([]);
        setInvestorRows([]);
        setSourceHealth(null);
        setStockState("error");
        setDataState("idle");
        onSelectStockRef.current(null);
        publishStatus({
          type: "error",
          text: apiErrorMessage(error, t("krMarket.errors.masterLoadFailed")),
        });
      }
    },
    [loadStockData, publishStatus, t]
  );

  async function refreshDailyPrices() {
    if (!selectedStock) return;
    setRefreshing(true);
    publishStatus(null);

    try {
      const indexConfig = getKrMarketIndexConfig(selectedStock.symbol);
      if (indexConfig) {
        if (timeframe === "today") {
          const today = await fetchKrIndexIntradayTrend(indexConfig.indexId, true);
          applyTodayTrend(today);
          publishStatus({
            type: today.warnings?.length ? "warning" : "success",
            text: t("dashboard.marketIndex.krUpdated", {
              asOf: formatKoreaDateTime(today.points[today.points.length - 1]?.time),
            }),
          });
          return;
        }

        const refreshResult = await requestJson<KRIndexRefreshResultRead>(
          `/api/kr-market/indices/${encodeURIComponent(indexConfig.indexId)}/refresh`,
          { method: "POST" },
          { outputsize: "compact" }
        );
        publishStatus({
          type: isRefreshSuccess(refreshResult.status) ? "success" : "warning",
          text: t("krMarket.indices.refreshSuccess", {
            index: refreshResult.index_id,
            fetched: refreshResult.fetched_count,
            inserted: refreshResult.inserted_count,
            updated: refreshResult.updated_count,
          }),
        });
        await loadStockData(selectedStock.symbol, timeframe);
        return;
      }

      const refreshResult = await requestJson<KRDailyPriceRefreshResultRead>(
        `/api/kr-market/daily/${encodeURIComponent(selectedStock.symbol)}/refresh`,
        { method: "POST" },
        { outputsize: "compact", provider: "auto" }
      );
      publishStatus({
        type: isRefreshSuccess(refreshResult.status) ? "success" : "warning",
        text: t("krMarket.messages.dailyRefreshSuccess", {
          symbol: refreshResult.symbol,
          provider: refreshResult.provider,
          fetched: refreshResult.fetched_count,
          inserted: refreshResult.inserted_count,
          updated: refreshResult.updated_count,
        }),
      });
      await loadStockData(selectedStock.symbol, timeframe);
      await loadReadiness();
    } catch (error) {
      publishStatus({
        type: "error",
        text: `${t("krMarket.errors.dailyRefreshFailed")}: ${apiErrorMessage(error, t("krMarket.errors.dataLoadFailed"))}`,
      });
    } finally {
      setRefreshing(false);
    }
  }

  async function refreshMarketBreadth() {
    if (!selectedIndexConfig || !selectedStock) return;
    setRefreshing(true);
    setIndexBreadthMessage(null);

    try {
      const result = await requestJson<KRMarketBreadthRefreshResultRead>(
        "/api/kr-market/market-breadth/refresh",
        { method: "POST" },
        {
          market_id: "ALL",
          ...(latest?.time ? { trade_date: latest.time.slice(0, 10) } : {}),
        }
      );
      await loadStockData(selectedStock.symbol, timeframe);
      setIndexBreadthMessage({
        type: isRefreshSuccess(result.status) ? "success" : "warning",
        text: t("krMarket.messages.marketBreadthRefreshSuccess", {
          fetched: result.fetched_count,
          inserted: result.inserted_count,
          updated: result.updated_count,
        }),
      });
    } catch (error) {
      setIndexBreadthMessage({
        type: "error",
        text: `${t("krMarket.messages.marketBreadthRefreshFailed")}: ${apiErrorMessage(error, t("krMarket.errors.dataLoadFailed"))}`,
      });
    } finally {
      setRefreshing(false);
    }
  }

  async function refreshActiveResourceSlot() {
    if (!selectedStock) return;
    const resourceLabel = t(`krMarket.dataSlots.${activeDataSlot}.label`);
    setRefreshing(true);
    publishStatus(null);

    try {
      const refreshResult = await requestJson<KRResourceRefreshResultRead>(
        `/api/kr-market/resources/${encodeURIComponent(selectedStock.symbol)}/refresh`,
        { method: "POST" },
        { resource: activeDataSlot }
      );

      if (isRefreshSuccess(refreshResult.status)) {
        publishStatus({
          type: "success",
          text: t("krMarket.messages.resourceRefreshSuccess", {
            resource: resourceLabel,
            symbol: refreshResult.symbol ?? selectedStock.symbol,
            fetched: refreshResult.fetched_count,
            inserted: refreshResult.inserted_count,
            updated: refreshResult.updated_count,
          }),
        });
      } else if (refreshResult.status === "empty" || refreshResult.status === "planned") {
        publishStatus({
          type: "warning",
          text: t("krMarket.messages.resourceRefreshEmpty", {
            resource: resourceLabel,
            symbol: refreshResult.symbol ?? selectedStock.symbol,
          }),
        });
      } else if (refreshResult.status === "skipped") {
        publishStatus({
          type: "warning",
          text: t("krMarket.messages.resourceRefreshUnavailable", {
            resource: resourceLabel,
          }),
        });
      } else {
        publishStatus({
          type: "error",
          text: `${t("krMarket.messages.resourceRefreshFailed", { resource: resourceLabel })}: ${refreshResult.message}`,
        });
      }

      await loadStockData(selectedStock.symbol, timeframe);
      await loadReadiness();
    } catch (error) {
      publishStatus({
        type: "error",
        text: `${t("krMarket.messages.resourceRefreshFailed", { resource: resourceLabel })}: ${apiErrorMessage(error, t("krMarket.errors.dataLoadFailed"))}`,
      });
    } finally {
      setRefreshing(false);
    }
  }

  async function syncSymbolMaster() {
    setRefreshing(true);
    publishStatus(null);

    try {
      const result = await requestJson<KRStockMasterSyncResultRead>(
        "/api/kr-market/stocks/sync-symbols",
        { method: "POST" }
      );
      publishStatus({
        type: "success",
        text: t("krMarket.messages.syncSuccess", {
          scanned: result.scanned_count,
          created: result.created_count,
          updated: result.updated_count,
        }),
      });
      await loadReadiness();
    } catch (error) {
      publishStatus({
        type: "error",
        text: `${t("krMarket.errors.syncFailed")}: ${apiErrorMessage(error, t("krMarket.errors.dataLoadFailed"))}`,
      });
    } finally {
      setRefreshing(false);
    }
  }

  function handleTimeframeChange(nextTimeframe: KRChartTimeframe) {
    setTimeframe(nextTimeframe);
  }

  useEffect(() => {
    if (!initialSymbol) return;

    // Symbol/timeframe/refresh nonce changes are the external signals for fetching KR data.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadStockBySymbol(initialSymbol, timeframe);
  }, [initialSymbol, loadStockBySymbol, refreshNonce, timeframe]);

  useEffect(() => {
    if (!initialSymbol) return;

    // Watchlist readiness is a group-level backend snapshot tied to the active KR surface.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadReadiness();
  }, [initialSymbol, loadReadiness, refreshNonce]);

  useEffect(() => {
    if (!selectedIndexId || timeframe !== "today") {
      return;
    }

    const effectIndexId = selectedIndexId;

    let cancelled = false;
    let intradayTimer: number | undefined;
    let intradayRequestInFlight = false;

    function clearIntradayTimer() {
      if (intradayTimer !== undefined) {
        window.clearTimeout(intradayTimer);
        intradayTimer = undefined;
      }
    }

    async function refreshTodayTrend(showLoading: boolean) {
      if (intradayRequestInFlight) return;
      intradayRequestInFlight = true;

      if (showLoading) {
        setTodayIntradayState("loading");
        setTodayIntradayMessage(null);
        setTodayUpdatedAt(null);
        setTodayTrend([]);
      }

      try {
        const today = await fetchKrIndexIntradayTrend(effectIndexId);

        if (cancelled) return;

        applyTodayTrend(today);
      } catch (error) {
        if (cancelled) return;

        setTodayIntradayState("error");
        setTodayIntradayMessage({
          type: "error",
          text: apiErrorMessage(error, t("krMarket.errors.dataLoadFailed")),
        });
      } finally {
        intradayRequestInFlight = false;
      }
    }

    function scheduleTodayRefresh() {
      if (cancelled) return;

      const marketState = getKoreaMarketRefreshState();

      if (marketState.isPollingWindow) {
        intradayTimer = window.setTimeout(() => {
          void refreshTodayTrend(false).finally(scheduleTodayRefresh);
        }, KOREA_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalIntradayRefreshDate.current !== marketState.dateKey
      ) {
        finalIntradayRefreshDate.current = marketState.dateKey;
        intradayTimer = window.setTimeout(() => {
          void refreshTodayTrend(false).finally(scheduleTodayRefresh);
        }, 0);
        return;
      }

      intradayTimer = window.setTimeout(
        scheduleTodayRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    void refreshTodayTrend(true).finally(scheduleTodayRefresh);

    return () => {
      cancelled = true;
      clearIntradayTimer();
    };
  }, [applyTodayTrend, selectedIndexId, t, timeframe]);

  if (!initialSymbol) {
    return watchlistRankingPanel ? (
      <div className="min-w-0 space-y-4">
        <section className="min-w-0">{watchlistRankingPanel}</section>
      </div>
    ) : (
      <div className="min-w-0 space-y-4">
        <section className="border border-omi-border-subtle bg-omi-surface px-5 py-10 text-sm text-omi-text-muted">
          <div className="max-w-xl">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              {t(isSelectedIndex ? "krMarket.sections.index" : "krMarket.sections.stock")}
            </div>
            <h2 className="mt-2 text-2xl font-bold text-omi-text-strong">
              {t("krMarket.empty.noStockSelected")}
            </h2>
            <p className="mt-2 text-sm text-omi-text-muted">
              {t("krMarket.empty.selectStockPrompt")}
            </p>
            <button
              type="button"
              className="mt-4 h-9 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => void syncSymbolMaster()}
              disabled={refreshing}
            >
              {refreshing ? t("krMarket.actions.syncing") : t("krMarket.actions.syncMaster")}
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="w-full space-y-4">
      <section className="grid w-full grid-cols-1 items-start justify-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]">
        <div className="min-w-0 space-y-4 self-start">
          <section className="border border-omi-border-subtle bg-omi-surface">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 px-5 py-4">
              <div className="min-w-0">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                  {t(isSelectedIndex ? "krMarket.sections.index" : "krMarket.sections.stock")}
                </div>
                <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
                  {selectedTitle}
                </h2>
                <div className="mt-1 text-sm text-omi-text-muted">{selectedSubtitle}</div>
              </div>

              <div className="shrink-0 text-right">
                <PriceUpdatePulse
                  value={displayPrice}
                  direction={displayChange}
                  resetKey={`${selectedStock?.symbol ?? initialSymbol}:${timeframe}:${
                    todayTrend.length
                  }`}
                  className="text-3xl font-black text-omi-text-strong"
                >
                  {formatNumber(displayPrice, 2)}
                </PriceUpdatePulse>
                <div className={`text-sm font-bold ${priceToneClass(displayPct)}`}>
                  {formatSignedNumber(displayChange)} / {formatSignedPct(displayPct)}
                </div>
                <div className="mt-3 inline-flex border border-omi-border-subtle bg-omi-surface-subtle p-1">
                  {timeframeOptions.map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => handleTimeframeChange(option)}
                      className={[
                        "h-8 min-w-12 px-3 text-sm font-semibold transition",
                        timeframe === option
                          ? "omi-timeframe-tab-active"
                          : "text-omi-text-muted hover:bg-omi-surface",
                      ].join(" ")}
                    >
                      {timeframeLabel(t, option)}
                    </button>
                  ))}
                </div>
                <div className="mt-2 flex items-start justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => void refreshDailyPrices()}
                    className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={refreshing || !selectedStock}
                  >
                    {refreshing
                      ? t("krMarket.actions.refreshing")
                      : t(isSelectedIndex ? "krMarket.actions.refreshIndex" : "krMarket.actions.refreshDaily")}
                  </button>
                </div>
              </div>
            </div>

            {isIntradayTimeframe ? (
              <>
                {todayIntradayMessage ? (
                  <div
                    className={`border-t px-5 py-3 text-xs ${messageToneClass(
                      todayIntradayMessage.type
                    )}`}
                  >
                    {todayIntradayMessage.text}
                  </div>
                ) : null}
                {todayChartLoading ? (
                  <div className="flex h-[420px] items-center justify-center border-t border-omi-border-subtle text-sm text-omi-text-muted">
                    {t("common.loading")}
                  </div>
                ) : (
                  <IntradayTrendChart
                    points={todayTrend}
                    previousClose={todayPreviousClose}
                    label={`${
                      selectedIndexConfig?.displaySymbol ??
                      selectedStock?.symbol ??
                      initialSymbol ??
                      ""
                    } ${timeframeLabel(t, "today")}`}
                    source={todaySource}
                    indicators={intradayIndicators}
                    session={krIndexIntradaySession}
                    revealKey={`${selectedIndexId ?? "empty"}-${timeframe}-${todayTrend.length}`}
                    refreshIntervalMs={KOREA_INTRADAY_REFRESH_MS}
                    updatedAt={todayUpdatedAt}
                    priceLimitEnabled={false}
                  />
                )}
              </>
            ) : chartData.length > 0 ? (
              <StockKLineChart
                chartData={chartData}
                label={selectedStock?.symbol ?? initialSymbol}
                indicators={chartIndicators}
                indicatorParameters={defaultIndicatorParameters}
                revealKey={`${selectedStock?.symbol ?? initialSymbol}-${timeframe}-${chartData.length}`}
                volumePanelLabel={t("krMarket.metrics.volume")}
                volumeTooltipLabel={t("krMarket.metrics.volume")}
                volumeValueFormatter={formatWholeNumber}
              />
            ) : (
              <div className="flex h-[460px] items-center justify-center border-t border-omi-border-subtle text-sm text-omi-text-muted">
                {chartLoading
                  ? t("common.loading")
                  : t(isSelectedIndex ? "krMarket.empty.noIndexKline" : "krMarket.empty.noKline")}
              </div>
            )}
          </section>

          {!isSelectedIndex && watchlistRankingPanel ? (
            <div className="min-w-0">{watchlistRankingPanel}</div>
          ) : null}
        </div>

        <aside className="flex min-w-0 flex-col border border-omi-border-subtle bg-omi-surface">
          <section>
            <div className="flex items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                  {t("krMarket.sections.technical")}
                </div>
                <h3 className="mt-1 text-xl font-bold text-omi-text-strong">
                  {t("krMarket.technical.title")}
                </h3>
                <div className="mt-1 text-sm text-omi-text-muted">
                  {t("krMarket.technical.subtitle")}
                </div>
              </div>
              <div className={`text-right text-lg font-black ${priceToneClass(priceVsMa20)}`}>
                {formatSignedPct(priceVsMa20)}
                <div className="text-xs font-semibold text-omi-text-muted">vs MA20</div>
              </div>
            </div>

            <div className="divide-y divide-omi-border-subtle px-5 text-sm">
              {technicalRows.map((row) => (
                <div key={row.label} className="py-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-bold text-omi-text-strong">{row.label}</div>
                    <div className={`font-black tabular-nums ${priceToneClass(row.tone)}`}>
                      {row.value}
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-omi-text-muted">{row.detail}</div>
                </div>
              ))}
            </div>
          </section>

          {selectedIndexConfig ? (
            <>
              <div className="h-2 border-y border-omi-border-subtle bg-omi-surface-muted" aria-hidden="true" />
              <section className="px-5 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                  {t("krMarket.sections.indexData")}
                </div>
                <h3 className="mt-1 text-lg font-bold text-omi-text-strong">
                  {selectedIndexConfig.name}
                </h3>
                <div className="mt-1 text-sm leading-6 text-omi-text-muted">
                  {t("krMarket.indexDataDescription")}
                </div>
                <div className="mt-4 grid grid-cols-2 gap-px bg-omi-border-subtle">
                  <MetricCell label={t("krMarket.metrics.symbol")} value={selectedIndexConfig.indexId} />
                  <MetricCell label={t("krMarket.metrics.display")} value={selectedIndexConfig.displaySymbol} />
                  <MetricCell label={t("krMarket.metrics.exchange")} value={selectedIndexConfig.exchange} />
                  <MetricCell label={t("krMarket.metrics.segment")} value={selectedIndexConfig.marketSegment} />
                  <MetricCell label={t("krMarket.metrics.source")} value={chart?.backfill?.provider ? String(chart.backfill.provider) : "KR index daily"} />
                  <MetricCell label={t("dashboard.marketIndex.candleCount")} value={formatWholeNumber(chartData.length)} />
                </div>
                <div className="mt-5 border-t border-omi-border-subtle pt-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                        {t("krMarket.sections.marketBreadth")}
                      </div>
                      <div className="mt-1 text-sm leading-6 text-omi-text-muted">
                        {indexBreadth?.coverage_note ?? t("krMarket.marketBreadthDescription")}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="h-8 shrink-0 border border-omi-control bg-omi-surface px-3 text-xs font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger disabled:cursor-not-allowed disabled:opacity-60"
                      onClick={() => void refreshMarketBreadth()}
                      disabled={refreshing || !selectedStock}
                    >
                      {refreshing ? t("krMarket.actions.refreshing") : t("krMarket.actions.refreshBreadth")}
                    </button>
                  </div>
                  {indexBreadthMessage ? (
                    <div className={`mt-3 border px-3 py-2 text-xs ${messageToneClass(indexBreadthMessage.type)}`}>
                      {indexBreadthMessage.text}
                    </div>
                  ) : null}
                  {indexBreadth && indexBreadth.total_count > 0 ? (
                    <>
                      <div className="mt-4 grid grid-cols-2 gap-px bg-omi-border-subtle">
                        {indexBreadthRows.map((item) => (
                          <MetricCell key={item.label} label={item.label} value={item.value} />
                        ))}
                      </div>
                      <div className="mt-2 text-xs text-omi-text-muted">
                        {t("krMarket.metrics.source")} {indexBreadth.source ?? "-"}
                        {" 繚 "}
                        {t("krMarket.indices.dataDate", {
                          date: formatDate(indexBreadth.trade_date),
                        })}
                      </div>
                    </>
                  ) : (
                    <div className="mt-4 border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3 text-xs text-omi-text-muted">
                      {dataState === "loading" ? t("common.loading") : t("krMarket.marketBreadthEmpty")}
                    </div>
                  )}
                </div>
              </section>
            </>
          ) : (
            <>
              <div className="h-2 border-y border-omi-border-subtle bg-omi-surface-muted" aria-hidden="true" />

        <section className="border-b border-omi-border-subtle px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("krMarket.sections.readiness")}
              </div>
              <div className="mt-1 truncate text-sm font-semibold text-omi-text">
                {readinessBadge}
              </div>
            </div>
            <span
              className={`shrink-0 border px-2 py-1 text-[11px] font-bold ${readinessStatusClass(selectedReadiness?.readiness_status ?? readinessState)}`}
            >
              {t(readinessStatusLabelKey(selectedReadiness?.readiness_status ?? readinessState))}
            </span>
          </div>

          {watchlistReadiness ? (
            <>
              <div className="mt-3 grid grid-cols-4 gap-1.5 text-center text-xs">
                {readinessSummaryCards.map((card) => (
                  <div key={card.label} className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
                    <div className="font-bold text-omi-text-strong">{card.value}</div>
                    <div className="mt-0.5 truncate text-omi-text-muted">{card.label}</div>
                  </div>
                ))}
              </div>
              {selectedReadinessCells.length ? (
                <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {selectedReadinessCells.map((item) => (
                    <ReadinessCell
                      key={item.label}
                      label={item.label}
                      status={item.status}
                      detail={item.detail}
                    />
                  ))}
                </div>
              ) : null}
              <div className="mt-2 text-xs text-omi-text-muted">
                {selectedReadinessMissingText}
                {watchlistReadiness.expected_daily_price_date ? (
                  <span className="ml-2">
                    {" · "}
                    {t("krMarket.readiness.expectedDaily", {
                      date: formatDate(watchlistReadiness.expected_daily_price_date),
                    })}
                  </span>
                ) : null}
              </div>
            </>
          ) : (
            <div className="mt-3 border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3 text-xs text-omi-text-muted">
              {readinessState === "loading" ? t("krMarket.readiness.loading") : t("krMarket.readiness.unavailable")}
            </div>
          )}
        </section>

        <section className="border-b border-omi-border-subtle px-5 py-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("krMarket.sections.sourceHealth")}
          </div>
          <div className="mt-2 grid grid-cols-4 gap-2 text-center text-xs">
            {[
              ["OK", sourceHealth?.summary.ok_count],
              ["Empty", sourceHealth?.summary.empty_count],
              ["Stale", sourceHealth?.summary.stale_count],
              ["Error", sourceHealth?.summary.error_count],
            ].map(([label, value]) => (
              <div key={label} className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
                <div className="font-bold text-omi-text-strong">{value ?? "-"}</div>
                <div className="mt-0.5 text-omi-text-muted">{label}</div>
              </div>
            ))}
          </div>
          <div className="mt-2 truncate text-xs text-omi-text-muted">
            {sourceHealth?.entries[0]?.reason ?? t("common.noData")}
          </div>
        </section>

        <div className="bg-omi-surface">
          <ResourceSlotTabs
            activeKey={activeDataSlot}
            labels={resourceSlotLabels}
            onActiveKeyChange={setActiveDataSlot}
            slots={resourceSlotItems}
            statusLabel={(status) => t(resourceStatusLabelKey(status))}
            statusToneClass={resourceStatusClass}
            footer={
              <>
                <div className="border-b border-omi-border-subtle px-5 py-4 text-sm">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                    {activeSlotDetail.eyebrow}
                  </div>
                  <h3 className="mt-1 text-lg font-bold text-omi-text-strong">
                    {activeSlotDetail.title}
                  </h3>
                  <div className="mt-1 text-xs text-omi-text-muted">
                    {activeSlotDetail.subtitle}
                  </div>
                  <button
                    type="button"
                    className="mt-3 h-8 border border-omi-control bg-omi-surface px-3 text-xs font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger disabled:cursor-not-allowed disabled:opacity-60"
                    onClick={() => void refreshActiveResourceSlot()}
                    disabled={refreshing || !selectedStock}
                  >
                    {refreshing ? t("krMarket.actions.refreshing") : t("krMarket.actions.refreshSlot")}
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-px bg-omi-border-subtle">
                  {activeSlotMetrics.map((item) => (
                    <MetricCell key={item.label} label={item.label} value={item.value} />
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-px bg-omi-border-subtle">
                  {headerMetrics.map((item) => (
                    <MetricCell key={item.label} label={item.label} value={item.value} />
                  ))}
                </div>
              </>
            }
          />
        </div>
            </>
          )}
      </aside>
      </section>
    </div>
  );
}

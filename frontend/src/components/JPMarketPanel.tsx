"use client";

import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import ProfessionalChartPanel, {
  type ProfessionalChartStyle,
} from "@/components/ProfessionalChartPanel";
import ResourceSlotTabs from "@/components/market-detail/ResourceSlotTabs";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  type IndicatorKey,
  type IndicatorParameters,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import type { ChartDrawing, ChartDrawingTool } from "@/components/LightweightKLineChart";
import type { ResourceSlotTabItem } from "@/components/market-detail/types";
import TechnicalIndicatorMenu, {
  indicatorTemplates,
  type IndicatorTemplateKey,
} from "@/components/stock-detail/TechnicalIndicatorMenu";
import {
  chartDrawingSnapshotsEqual,
  createChartDrawingSnapshot,
  loadChartDrawings,
  normalizeChartDrawingSelection,
  saveChartDrawings,
  serializeChartDrawings,
  type ChartDrawingHistoryState,
  type ChartDrawingStorageState,
} from "@/components/professionalChartDrawing";
import { timeframeLabel, useT } from "@/i18n";
import { fetchJson, requestJson } from "@/lib/api";
import { getJpMarketIndexConfig } from "@/lib/jpMarketIndices";
import type {
  ChartPoint,
  JPCompanyFundamentalRead,
  JPOhlcChartRead,
  JPOhlcPointRead,
  JPResourceSummaryRead,
  JPResourceRefreshResultRead,
  JPStockMasterRead,
} from "@/types/market";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type Message = { type: "success" | "warning" | "error"; text: string } | null;
type JPChartTimeframe = "today" | "daily" | "weekly" | "monthly";
type JPProfessionalTimeframe = Exclude<JPChartTimeframe, "today">;
type JPDataSlot = "demand" | "investors" | "disclosures" | "performance" | "financials";

type Props = {
  initialSymbol: string | null;
  refreshNonce?: number;
  watchlistRankingPanel?: ReactNode;
  onChartFocusModeChange?: (enabled: boolean) => void;
  onSelectStock: (stock: JPStockMasterRead | null) => void;
  onStatusMessage?: (message: Message) => void;
};

const timeframeOptions: JPChartTimeframe[] = ["today", "daily", "weekly", "monthly"];
const professionalTimeframeOptions: JPProfessionalTimeframe[] = ["daily", "weekly", "monthly"];
const barsByTimeframe: Record<JPChartTimeframe, number> = {
  today: 60,
  daily: 180,
  weekly: 104,
  monthly: 72,
};
const jpDataSlots: Array<{ key: JPDataSlot; titleKey: string; descriptionKey: string }> = [
  {
    key: "demand",
    titleKey: "jpMarket.dataSlots.demand.title",
    descriptionKey: "jpMarket.dataSlots.demand.description",
  },
  {
    key: "investors",
    titleKey: "jpMarket.dataSlots.investors.title",
    descriptionKey: "jpMarket.dataSlots.investors.description",
  },
  {
    key: "disclosures",
    titleKey: "jpMarket.dataSlots.disclosures.title",
    descriptionKey: "jpMarket.dataSlots.disclosures.description",
  },
  {
    key: "performance",
    titleKey: "jpMarket.dataSlots.performance.title",
    descriptionKey: "jpMarket.dataSlots.performance.description",
  },
  {
    key: "financials",
    titleKey: "jpMarket.dataSlots.financials.title",
    descriptionKey: "jpMarket.dataSlots.financials.description",
  },
];

const jpChartIndicators: IndicatorSettings = {
  ...defaultIndicators,
  ma: true,
  volume: true,
  signals: false,
};

function chartDrawingStorageKey(symbol: string | null, timeframe: JPProfessionalTimeframe) {
  return `omi:jp:chart-drawings:v1:${symbol ?? "empty"}:${timeframe}`;
}

function apiErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function isRefreshSuccess(status: string | null | undefined) {
  return status === "success" || status === "partial_success";
}

function normalizeSymbolInput(value: string) {
  const input = value.trim().toUpperCase();
  if (!input) return "";

  const token = input.includes(":") ? input.split(":").pop()?.trim() ?? input : input;
  return token.replace(/\s+/g, "");
}

function formatNumber(value: number | null | undefined, maximumFractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("en-US", {
    maximumFractionDigits,
  });
}

function formatVolume(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("en-US");
}

function formatCompactMoney(
  value: number | null | undefined,
  currency: string | null | undefined
) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const prefix = currency === "JPY" ? "¥" : currency ? `${currency} ` : "";
  const absValue = Math.abs(value);
  if (absValue >= 1_000_000_000_000) return `${prefix}${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (absValue >= 1_000_000_000) return `${prefix}${(value / 1_000_000_000).toFixed(2)}B`;
  if (absValue >= 1_000_000) return `${prefix}${(value / 1_000_000).toFixed(2)}M`;
  return `${prefix}${formatNumber(value, 0)}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function formatSignedNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, 2)}`;
}

function formatSignedVolume(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatVolume(value)}`;
}

function formatSignedPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${formatSignedNumber(value)}%`;
}

function formatRatioAsPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${formatNumber(normalized, 2)}%`;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

function positiveRatio(numerator: number | null | undefined, denominator: number | null | undefined) {
  if (!isFiniteNumber(numerator) || !isFiniteNumber(denominator) || denominator <= 0) {
    return null;
  }

  return numerator / denominator;
}

function formatPlainRatio(value: number | null | undefined) {
  if (!isFiniteNumber(value)) return "-";
  return formatNumber(value, 2);
}

function priceToneClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "text-omi-text-muted";
  if (value > 0) return "text-omi-danger";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text-muted";
}

function resourceStatusClass(status: string | null | undefined) {
  if (status === "available") return "text-omi-market-down";
  if (status === "empty") return "text-omi-warning";
  if (status === "error") return "text-omi-danger";
  if (status === "stale") return "text-omi-warning";
  if (status === "loading") return "text-omi-accent";
  return "text-omi-text-muted";
}

function resourceStatusLabelKey(status: string | null | undefined) {
  if (status === "available") return "jpMarket.dataSlots.statusLabels.available";
  if (status === "empty") return "jpMarket.dataSlots.statusLabels.empty";
  if (status === "error") return "jpMarket.dataSlots.statusLabels.error";
  if (status === "stale") return "jpMarket.dataSlots.statusLabels.stale";
  if (status === "loading") return "jpMarket.dataSlots.statusLabels.loading";
  return "jpMarket.dataSlots.statusLabels.planned";
}

function formatFundamentalProvider(provider: string | null | undefined) {
  if (!provider) return "-";
  return provider
    .split("+")
    .map((item) => {
      if (item === "jquants_statements") return "J-Quants";
      if (item === "yahoo_quote_summary") return "Yahoo";
      return item;
    })
    .join(" + ");
}

function toChartPoint(point: JPOhlcPointRead): ChartPoint {
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
  if (previous?.close === null || previous?.close === undefined || previous.close === 0) {
    return null;
  }

  return (change / previous.close) * 100;
}

function movingAverage(
  points: ChartPoint[],
  key: "close" | "volume",
  windowSize: number
) {
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

async function fetchOptionalJson<T>(
  path: string,
  params?: Record<string, string | number | boolean>
) {
  try {
    return await fetchJson<T>(path, params);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("API 404:")) {
      return null;
    }

    throw error;
  }
}

export default function JPMarketPanel({
  initialSymbol,
  refreshNonce = 0,
  watchlistRankingPanel,
  onChartFocusModeChange,
  onSelectStock,
  onStatusMessage,
}: Props) {
  const t = useT();
  const onSelectStockRef = useRef(onSelectStock);
  const onStatusMessageRef = useRef(onStatusMessage);
  const fundamentalAutoRefreshAttemptedRef = useRef<Set<string>>(new Set());
  const resourceAutoRefreshAttemptedRef = useRef<Set<string>>(new Set());
  const [selectedStock, setSelectedStock] = useState<JPStockMasterRead | null>(null);
  const [chart, setChart] = useState<JPOhlcChartRead | null>(null);
  const [resourceSummary, setResourceSummary] = useState<JPResourceSummaryRead | null>(null);
  const [fundamental, setFundamental] = useState<JPCompanyFundamentalRead | null>(null);
  const [timeframe, setTimeframe] = useState<JPChartTimeframe>("daily");
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [chartFocusMode, setChartFocusMode] = useState(false);
  const [professionalTimeframe, setProfessionalTimeframe] =
    useState<JPProfessionalTimeframe>("daily");
  const [professionalChartStyle, setProfessionalChartStyle] =
    useState<ProfessionalChartStyle>("candlestick");
  const [chartIndicators, setChartIndicators] =
    useState<IndicatorSettings>(jpChartIndicators);
  const [activeIndicatorTemplate, setActiveIndicatorTemplate] =
    useState<IndicatorTemplateKey | null>("basic");
  const [indicatorParameters, setIndicatorParameters] =
    useState<IndicatorParameters>(defaultIndicatorParameters);
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
  const [activeDataSlot, setActiveDataSlot] = useState<JPDataSlot>("demand");
  const [stockState, setStockState] = useState<LoadState>("idle");
  const [dataState, setDataState] = useState<LoadState>("idle");

  const chartData = useMemo<ChartPoint[]>(
    () => chart?.points.map(toChartPoint) ?? [],
    [chart]
  );
  const latest = latestPoint(chartData);
  const latestClose = latest?.close ?? null;
  const change = changeValue(chartData);
  const pct = changePct(chartData);
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
  const selectedTitle = selectedStock
    ? `${selectedStock.symbol} ${selectedStock.security_name ?? ""}`.trim()
    : t("jpMarket.empty.noStockSelected");
  const selectedSubtitle = selectedStock
    ? [
        selectedStock.exchange ?? "JPX",
        selectedStock.market_segment,
        selectedStock.sector_33_name,
        selectedStock.asset_type,
      ]
        .filter(Boolean)
        .join(" / ")
    : t("jpMarket.empty.selectStockPrompt");
  const chartLoading = stockState === "loading" || dataState === "loading";
  const resourceSlotLabels = useMemo(
    () => ({
      eyebrow: t("jpMarket.sections.marketData"),
      status: t("jpMarket.dataSlots.status"),
      source: t("jpMarket.dataSlots.source"),
      latestDate: t("jpMarket.dataSlots.latestDate"),
      rows: t("jpMarket.dataSlots.rows"),
      reserved: t("jpMarket.dataSlots.reserved"),
    }),
    [t]
  );
  const resourceSlotItems = useMemo<Array<ResourceSlotTabItem<JPDataSlot>>>(
    () =>
      jpDataSlots.map((slot) => {
        const resourceSlot =
          resourceSummary?.slots.find((item) => item.key === slot.key) ?? null;
        const status =
          dataState === "loading" ? "loading" : resourceSlot?.status ?? "planned";

        return {
          key: slot.key,
          label: t(`jpMarket.dataSlots.${slot.key}.label`),
          title: t(slot.titleKey),
          description: t(slot.descriptionKey),
          status,
          source: resourceSlot?.source ?? t("jpMarket.dataSlots.planned"),
          latestDate: resourceSlot?.latest_date ? formatDate(resourceSlot.latest_date) : "-",
          rowCount: resourceSlot === null ? "-" : formatNumber(resourceSlot.row_count, 0),
        };
      }),
    [dataState, resourceSummary, t]
  );
  const activeResourceSlot = useMemo(
    () => resourceSummary?.slots.find((item) => item.key === activeDataSlot) ?? null,
    [activeDataSlot, resourceSummary]
  );
  const activeSlotDetail = useMemo(() => {
    const hasFundamentalSlot = activeDataSlot === "performance" || activeDataSlot === "financials";
    const provider = formatFundamentalProvider(fundamental?.provider);
    const disclosedDate = formatDate(fundamental?.disclosed_date);
    const fetchedAt = formatDate(fundamental?.fetched_at);

    return {
      eyebrow: t("jpMarket.slotDetails.eyebrow"),
      title: t(`jpMarket.slotDetails.${activeDataSlot}.title`),
      subtitle:
        hasFundamentalSlot && fundamental
          ? `${provider} · ${disclosedDate} · ${fundamental.fiscal_period ?? "-"} · ${t(
              "jpMarket.slotMetrics.fetchedAt"
            )} ${fetchedAt}`
          : t(`jpMarket.slotDetails.${activeDataSlot}.empty`),
    };
  }, [activeDataSlot, fundamental, t]);

  const activeSlotMetrics = useMemo(() => {
    const slotMetrics = activeResourceSlot?.metrics ?? {};
    const metricNumber = (key: string) => {
      const value = slotMetrics[key];
      return typeof value === "number" && Number.isFinite(value) ? value : null;
    };
    const metricText = (key: string) => {
      const value = slotMetrics[key];
      if (typeof value === "string" && value.trim()) return value;
      if (typeof value === "number" && Number.isFinite(value)) return formatNumber(value, 0);
      return "-";
    };
    const derivedMarketCap =
      fundamental?.market_cap ??
      (isFiniteNumber(latestClose) && isFiniteNumber(fundamental?.shares_outstanding)
        ? latestClose * fundamental.shares_outstanding
        : null);
    const trailingPe =
      fundamental?.trailing_pe ?? positiveRatio(latestClose, fundamental?.eps_ttm);
    const forwardPe =
      fundamental?.forward_pe ?? positiveRatio(latestClose, fundamental?.forward_eps);
    const priceToBook =
      fundamental?.price_to_book ?? positiveRatio(latestClose, fundamental?.book_value);
    const freeCashFlow =
      isFiniteNumber(fundamental?.operating_cash_flow) && isFiniteNumber(fundamental?.investing_cash_flow)
        ? fundamental.operating_cash_flow + fundamental.investing_cash_flow
        : null;

    if (activeDataSlot === "performance") {
      return [
        {
          label: t("jpMarket.slotMetrics.disclosedDate"),
          value: formatDate(fundamental?.disclosed_date),
        },
        {
          label: t("jpMarket.slotMetrics.fiscalPeriod"),
          value: fundamental?.fiscal_period ?? "-",
        },
        {
          label: t("jpMarket.slotMetrics.fiscalYearEnd"),
          value: formatDate(fundamental?.fiscal_year_end),
        },
        {
          label: t("jpMarket.slotMetrics.documentType"),
          value: fundamental?.document_type ?? "-",
        },
        {
          label: t("jpMarket.slotMetrics.netSales"),
          value: formatCompactMoney(
            fundamental?.net_sales ?? fundamental?.revenue_ttm,
            fundamental?.currency
          ),
        },
        {
          label: t("jpMarket.slotMetrics.operatingProfit"),
          value: formatCompactMoney(fundamental?.operating_profit, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.ordinaryProfit"),
          value: formatCompactMoney(fundamental?.ordinary_profit, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.profit"),
          value: formatCompactMoney(fundamental?.profit, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.forecastNetSales"),
          value: formatCompactMoney(fundamental?.forecast_net_sales, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.forecastOperatingProfit"),
          value: formatCompactMoney(fundamental?.forecast_operating_profit, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.forecastOrdinaryProfit"),
          value: formatCompactMoney(fundamental?.forecast_ordinary_profit, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.forecastProfit"),
          value: formatCompactMoney(fundamental?.forecast_profit, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.revenueGrowth"),
          value: formatRatioAsPct(fundamental?.revenue_growth),
        },
        {
          label: t("jpMarket.slotMetrics.operatingMargin"),
          value: formatRatioAsPct(fundamental?.operating_margin),
        },
        {
          label: t("jpMarket.slotMetrics.earningsGrowth"),
          value: formatRatioAsPct(fundamental?.earnings_growth),
        },
        {
          label: t("jpMarket.slotMetrics.profitMargin"),
          value: formatRatioAsPct(fundamental?.profit_margin),
        },
      ];
    }

    if (activeDataSlot === "financials") {
      return [
        {
          label: t("jpMarket.slotMetrics.totalAssets"),
          value: formatCompactMoney(fundamental?.total_assets, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.marketCap"),
          value: formatCompactMoney(derivedMarketCap, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.pe"),
          value: formatPlainRatio(trailingPe),
        },
        {
          label: t("jpMarket.slotMetrics.forwardPe"),
          value: formatPlainRatio(forwardPe),
        },
        {
          label: t("jpMarket.slotMetrics.pb"),
          value: formatPlainRatio(priceToBook),
        },
        {
          label: t("jpMarket.slotMetrics.epsTtm"),
          value: formatNumber(fundamental?.eps_ttm, 2),
        },
        {
          label: t("jpMarket.slotMetrics.forwardEps"),
          value: formatNumber(fundamental?.forward_eps, 2),
        },
        {
          label: t("jpMarket.slotMetrics.bookValue"),
          value: formatNumber(fundamental?.book_value, 2),
        },
        {
          label: t("jpMarket.slotMetrics.equity"),
          value: formatCompactMoney(fundamental?.equity, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.equityRatio"),
          value: formatRatioAsPct(fundamental?.equity_to_asset_ratio),
        },
        {
          label: t("jpMarket.slotMetrics.sharesOutstanding"),
          value: formatVolume(fundamental?.shares_outstanding),
        },
        {
          label: t("jpMarket.slotMetrics.cashAndEquivalents"),
          value: formatCompactMoney(fundamental?.total_cash, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.roe"),
          value: formatRatioAsPct(fundamental?.return_on_equity),
        },
        {
          label: t("jpMarket.slotMetrics.roa"),
          value: formatRatioAsPct(fundamental?.return_on_assets),
        },
        {
          label: t("jpMarket.slotMetrics.debtToEquity"),
          value: formatRatioAsPct(fundamental?.debt_to_equity),
        },
        {
          label: t("jpMarket.slotMetrics.operatingCashFlow"),
          value: formatCompactMoney(fundamental?.operating_cash_flow, fundamental?.currency),
        },
        {
          label: t("jpMarket.slotMetrics.freeCashFlow"),
          value: formatCompactMoney(freeCashFlow, fundamental?.currency),
        },
      ];
    }

    if (activeDataSlot === "demand") {
      return [
        {
          label: t("jpMarket.slotMetrics.marginBalance"),
          value: formatVolume(metricNumber("margin_long_balance")),
        },
        {
          label: t("jpMarket.slotMetrics.shortSelling"),
          value: formatVolume(metricNumber("margin_short_balance")),
        },
        {
          label: t("jpMarket.slotMetrics.lendingBalance"),
          value: formatSignedVolume(metricNumber("margin_net_balance")),
        },
        {
          label: t("jpMarket.slotMetrics.ownershipDistribution"),
          value: metricText("margin_issue_type"),
        },
      ];
    }

    if (activeDataSlot === "investors") {
      return [
        {
          label: t("jpMarket.slotMetrics.foreignInvestors"),
          value: formatSignedVolume(metricNumber("foreign_balance")),
        },
        {
          label: t("jpMarket.slotMetrics.trustBanks"),
          value: formatSignedVolume(metricNumber("trust_bank_balance")),
        },
        {
          label: t("jpMarket.slotMetrics.individuals"),
          value: formatSignedVolume(metricNumber("individual_balance")),
        },
        {
          label: t("jpMarket.slotMetrics.proprietary"),
          value: formatSignedVolume(metricNumber("proprietary_balance")),
        },
      ];
    }

    return [
      { label: t("jpMarket.slotMetrics.latestDisclosure"), value: "-" },
      { label: t("jpMarket.slotMetrics.earningsRelease"), value: "-" },
      { label: t("jpMarket.slotMetrics.forecastRevision"), value: "-" },
      { label: t("jpMarket.slotMetrics.largeShareholding"), value: "-" },
    ];
  }, [activeDataSlot, activeResourceSlot, fundamental, latestClose, t]);

  useEffect(() => {
    onSelectStockRef.current = onSelectStock;
  }, [onSelectStock]);

  useEffect(() => {
    onStatusMessageRef.current = onStatusMessage;
  }, [onStatusMessage]);

  useEffect(() => {
    onChartFocusModeChange?.(chartFocusMode);
  }, [chartFocusMode, onChartFocusModeChange]);

  useEffect(() => {
    return () => onChartFocusModeChange?.(false);
  }, [onChartFocusModeChange]);

  const headerMetrics = useMemo(
    () => [
      {
        label: t("jpMarket.metrics.date"),
        value: formatDate(latest?.time),
      },
      {
        label: t("jpMarket.metrics.close"),
        value: formatNumber(latest?.close, 2),
      },
      {
        label: t("jpMarket.metrics.volume"),
        value: formatVolume(latest?.volume),
      },
      {
        label: t("jpMarket.metrics.segment"),
        value: selectedStock?.market_segment ?? "-",
      },
      {
        label: t("jpMarket.metrics.sector"),
        value: selectedStock?.sector_33_name ?? "-",
      },
      {
        label: t("jpMarket.metrics.source"),
        value: chart?.backfill?.provider ? String(chart.backfill.provider) : "Yahoo chart",
      },
    ],
    [chart, latest?.close, latest?.time, latest?.volume, selectedStock, t]
  );

  const technicalRows = useMemo(
    () => [
      {
        label: t("jpMarket.technical.priceVsMa20"),
        value: formatSignedPct(priceVsMa20),
        tone: priceVsMa20,
        detail:
          ma20 === null
            ? t("common.noData")
            : `MA20 ${formatNumber(ma20, 2)}`,
      },
      {
        label: t("jpMarket.technical.volumeVsMa20"),
        value: formatSignedPct(volumeVsMa20),
        tone: volumeVsMa20,
        detail:
          volumeMa20 === null
            ? t("common.noData")
            : `${t("jpMarket.technical.volumeMa20")} ${formatVolume(volumeMa20)}`,
      },
      {
        label: t("jpMarket.metrics.change"),
        value: `${formatSignedNumber(change)} / ${formatSignedPct(pct)}`,
        tone: pct,
        detail: timeframeLabel(t, timeframe),
      },
    ],
    [change, ma20, pct, priceVsMa20, t, timeframe, volumeMa20, volumeVsMa20]
  );

  const selectedChartSymbol = selectedStock?.symbol ?? initialSymbol;
  const professionalTimeframeLabel = timeframeLabel(t, professionalTimeframe);
  const professionalChartReady =
    chartFocusMode && chartData.length > 0 && dataState !== "loading";
  const chartDrawingKey = chartDrawingStorageKey(selectedChartSymbol, professionalTimeframe);
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
  const professionalDrawingContext = useMemo(
    () => ({
      symbol: selectedChartSymbol,
      market: "JP",
      timeframe: professionalTimeframe,
    }),
    [professionalTimeframe, selectedChartSymbol]
  );

  const publishStatus = useCallback((nextMessage: Message) => {
    onStatusMessageRef.current?.(nextMessage);
  }, []);

  function handleTimeframeChange(nextTimeframe: JPChartTimeframe) {
    setTimeframe(nextTimeframe);
    setIndicatorMenuOpen(false);
    if (nextTimeframe !== "today") {
      setProfessionalTimeframe(nextTimeframe);
    }
  }

  function handleProfessionalTimeframeChange(nextTimeframe: JPProfessionalTimeframe) {
    setProfessionalTimeframe(nextTimeframe);
    setTimeframe(nextTimeframe);
    setIndicatorMenuOpen(false);
  }

  function enterChartFocusMode() {
    const nextTimeframe: JPProfessionalTimeframe =
      timeframe === "today" ? "daily" : timeframe;

    setProfessionalTimeframe(nextTimeframe);
    setTimeframe(nextTimeframe);
    setIndicatorMenuOpen(false);
    setChartFocusMode(true);
  }

  function toggleChartIndicator(key: IndicatorKey) {
    setChartIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
    setActiveIndicatorTemplate(null);
  }

  function applyIndicatorTemplate(templateKey: IndicatorTemplateKey) {
    const template = indicatorTemplates.find((item) => item.key === templateKey);
    if (!template) return;

    setChartIndicators(template.indicators);
    if (template.parameters) {
      setIndicatorParameters((current) => ({
        ...current,
        ...template.parameters,
      }));
    }
    setActiveIndicatorTemplate(templateKey);
  }

  function handleIndicatorParameterChange(
    key: keyof IndicatorParameters,
    value: string,
    min: number,
    max: number
  ) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;

    const nextValue = Math.min(Math.max(parsed, min), max);
    setIndicatorParameters((current) => ({
      ...current,
      [key]: nextValue,
    }));
    setActiveIndicatorTemplate(null);
  }

  function storeChartDrawings(
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave = activeSelectedChartDrawingId
  ) {
    const normalizedSelectedDrawingId = normalizeChartDrawingSelection(
      drawingsToSave,
      selectedDrawingIdToSave
    );

    setChartDrawingState({
      key: chartDrawingKey,
      drawings: drawingsToSave,
    });
    saveChartDrawings(chartDrawingKey, drawingsToSave);
    setSelectedChartDrawingId(normalizedSelectedDrawingId);
  }

  function updateChartDrawingState(
    nextDrawings: ChartDrawing[],
    nextSelectedDrawingId: string | null
  ) {
    const currentSnapshot = createChartDrawingSnapshot(
      chartDrawings,
      activeSelectedChartDrawingId
    );
    const nextSnapshot = createChartDrawingSnapshot(nextDrawings, nextSelectedDrawingId);

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

    const currentPast =
      chartDrawingHistoryState.key === chartDrawingKey ? chartDrawingHistoryState.past : [];

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: [...currentPast, currentSnapshot].slice(-50),
      future: [],
    });
    storeChartDrawings(nextSnapshot.drawings, nextSnapshot.selectedDrawingId);
  }

  function updateChartDrawings(nextDrawings: ChartDrawing[]) {
    updateChartDrawingState(nextDrawings, activeSelectedChartDrawingId);
  }

  function undoChartDrawing() {
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
  }

  function redoChartDrawing() {
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
  }

  function deleteSelectedChartDrawing() {
    if (!activeSelectedChartDrawingId) return;

    updateChartDrawings(
      chartDrawings.filter((drawing) => drawing.id !== activeSelectedChartDrawingId)
    );
    setSelectedChartDrawingId(null);
  }

  function clearChartDrawings() {
    if (chartDrawings.length === 0) return;

    updateChartDrawings([]);
    setSelectedChartDrawingId(null);
  }

  const loadStockData = useCallback(
    async (symbol: string, nextTimeframe: JPChartTimeframe) => {
      setDataState("loading");

      try {
        const requestTimeframe =
          nextTimeframe === "today" ? "daily" : nextTimeframe;
        const isIndexSymbol = getJpMarketIndexConfig(symbol) !== null;
        const [chartResult, resourceResult, fundamentalResult] = await Promise.allSettled([
          fetchJson<JPOhlcChartRead>(
            `/api/jp-market/ohlc/${encodeURIComponent(symbol)}`,
            {
              timeframe: requestTimeframe,
              bars: barsByTimeframe[nextTimeframe],
              ensure_history: !isIndexSymbol,
            }
          ),
          isIndexSymbol
            ? Promise.resolve<JPResourceSummaryRead | null>(null)
            : fetchJson<JPResourceSummaryRead>(
                `/api/jp-market/resources/${encodeURIComponent(symbol)}/summary`
              ),
          isIndexSymbol
            ? Promise.resolve<JPCompanyFundamentalRead | null>(null)
            : fetchOptionalJson<JPCompanyFundamentalRead>(
                `/api/jp-market/fundamentals/${encodeURIComponent(symbol)}`
              ),
        ]);

        if (chartResult.status === "rejected") {
          throw chartResult.reason;
        }

        let nextResourceSummary =
          resourceResult.status === "fulfilled" ? resourceResult.value : null;
        let nextFundamental =
          fundamentalResult.status === "fulfilled" ? fundamentalResult.value : null;
        let nextMessage: Message = null;

        if (
          !isIndexSymbol &&
          nextFundamental === null &&
          !fundamentalAutoRefreshAttemptedRef.current.has(symbol)
        ) {
          fundamentalAutoRefreshAttemptedRef.current.add(symbol);

          try {
            const refreshResult = await requestJson<JPResourceRefreshResultRead>(
              `/api/jp-market/fundamentals/${encodeURIComponent(symbol)}/refresh`,
              { method: "POST" }
            );

            if (isRefreshSuccess(refreshResult.status)) {
              const [refreshedResourceResult, refreshedFundamentalResult] =
                await Promise.allSettled([
                  fetchJson<JPResourceSummaryRead>(
                    `/api/jp-market/resources/${encodeURIComponent(symbol)}/summary`
                  ),
                  fetchOptionalJson<JPCompanyFundamentalRead>(
                    `/api/jp-market/fundamentals/${encodeURIComponent(symbol)}`
                  ),
                ]);

              if (refreshedResourceResult.status === "fulfilled") {
                nextResourceSummary = refreshedResourceResult.value;
              }
              if (refreshedFundamentalResult.status === "fulfilled") {
                nextFundamental = refreshedFundamentalResult.value;
              }

              nextMessage = {
                type: "success",
                text: t("jpMarket.messages.fundamentalRefreshSuccess", {
                  symbol: refreshResult.symbol,
                  fetched: refreshResult.fetched_count,
                  inserted: refreshResult.inserted_count,
                  updated: refreshResult.updated_count,
                }),
              };
            } else if (refreshResult.status === "skipped") {
              nextMessage = {
                type: "error",
                text: t("jpMarket.messages.fundamentalRefreshPending"),
              };
            }
          } catch (refreshError) {
            nextMessage = {
              type: "error",
              text: `${t("jpMarket.messages.fundamentalRefreshFailed")}: ${apiErrorMessage(
                refreshError,
                t("jpMarket.errors.dataLoadFailed")
              )}`,
            };
          }
        }

        setChart(chartResult.value);
        setResourceSummary(nextResourceSummary);
        setFundamental(nextFundamental);
        setDataState("success");
        if (nextMessage) {
          publishStatus(nextMessage);
        }
      } catch (error) {
        setChart(null);
        setResourceSummary(null);
        setFundamental(null);
        setDataState("error");
        publishStatus({
          type: "error",
          text: apiErrorMessage(error, t("jpMarket.errors.dataLoadFailed")),
        });
      }
    },
    [publishStatus, t]
  );

  const loadStockBySymbol = useCallback(
    async (symbol: string, nextTimeframe: JPChartTimeframe) => {
      const normalizedSymbol = normalizeSymbolInput(symbol);
      if (!normalizedSymbol) return;

      setStockState("loading");
      publishStatus(null);

      try {
        let stock: JPStockMasterRead;

        try {
          stock = await fetchJson<JPStockMasterRead>(
            `/api/jp-market/stocks/${encodeURIComponent(normalizedSymbol)}`
          );
        } catch (error) {
          const indexConfig = getJpMarketIndexConfig(normalizedSymbol);
          if (!indexConfig) {
            throw error;
          }

          stock = {
            id: 0,
            symbol: indexConfig.symbol,
            local_code: null,
            security_name: indexConfig.name,
            exchange: indexConfig.exchange,
            market_segment: null,
            sector_33_code: null,
            sector_33_name: null,
            sector_17_code: null,
            sector_17_name: null,
            size_code: null,
            size_name: null,
            asset_type: "index",
            listing_source: "market_index_config",
            currency: "JPY",
            exchange_timezone_name: "Asia/Tokyo",
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
        setFundamental(null);
        setStockState("error");
        setDataState("idle");
        onSelectStockRef.current(null);
        publishStatus({
          type: "error",
          text: apiErrorMessage(error, t("jpMarket.errors.masterLoadFailed")),
        });
      }
    },
    [loadStockData, publishStatus, t]
  );

  const refreshActiveResourceSlot = useCallback(
    async (symbol: string, slotKey: JPDataSlot) => {
      const resourceLabel = t(`jpMarket.dataSlots.${slotKey}.label`);

      try {
        const refreshResult = await requestJson<JPResourceRefreshResultRead>(
          `/api/jp-market/resources/${encodeURIComponent(symbol)}/refresh`,
          { method: "POST" },
          { resource: slotKey }
        );

        if (isRefreshSuccess(refreshResult.status) || refreshResult.status === "empty") {
          const refreshedResourceSummary = await fetchJson<JPResourceSummaryRead>(
            `/api/jp-market/resources/${encodeURIComponent(symbol)}/summary`
          );
          setResourceSummary(refreshedResourceSummary);
        }

        if (isRefreshSuccess(refreshResult.status)) {
          publishStatus({
            type: "success",
            text: t("jpMarket.messages.resourceRefreshSuccess", {
              resource: resourceLabel,
              symbol: refreshResult.symbol,
              fetched: refreshResult.fetched_count,
              inserted: refreshResult.inserted_count,
              updated: refreshResult.updated_count,
            }),
          });
          return;
        }

        if (refreshResult.status === "rate_limited") {
          publishStatus({
            type: "warning",
            text: t("jpMarket.messages.resourceRefreshRateLimited", {
              resource: resourceLabel,
            }),
          });
          return;
        }

        if (refreshResult.status === "skipped") {
          publishStatus({
            type: "warning",
            text: t("jpMarket.messages.resourceRefreshUnavailable", {
              resource: resourceLabel,
            }),
          });
          return;
        }

        if (refreshResult.status === "empty") {
          publishStatus({
            type: "warning",
            text: t("jpMarket.messages.resourceRefreshEmpty", {
              resource: resourceLabel,
              symbol: refreshResult.symbol,
            }),
          });
          return;
        }

        publishStatus({
          type: "error",
          text: `${t("jpMarket.messages.resourceRefreshFailed", {
            resource: resourceLabel,
          })}: ${refreshResult.message}`,
        });
      } catch (error) {
        publishStatus({
          type: "error",
          text: `${t("jpMarket.messages.resourceRefreshFailed", {
            resource: resourceLabel,
          })}: ${apiErrorMessage(error, t("jpMarket.errors.dataLoadFailed"))}`,
        });
      }
    },
    [publishStatus, t]
  );

  useEffect(() => {
    if (!selectedStock || !resourceSummary) return;
    if (stockState === "loading" || dataState === "loading") return;
    if (activeDataSlot !== "demand" && activeDataSlot !== "investors") return;
    if (!activeResourceSlot || activeResourceSlot.status !== "empty") return;

    const refreshKey = `${selectedStock.symbol}:${activeDataSlot}`;
    if (resourceAutoRefreshAttemptedRef.current.has(refreshKey)) return;

    resourceAutoRefreshAttemptedRef.current.add(refreshKey);
    void refreshActiveResourceSlot(selectedStock.symbol, activeDataSlot);
  }, [
    activeDataSlot,
    activeResourceSlot,
    dataState,
    refreshActiveResourceSlot,
    resourceSummary,
    selectedStock,
    stockState,
  ]);

  useEffect(() => {
    if (!initialSymbol) {
      return;
    }

    // Symbol/timeframe/refresh nonce changes are the external signals for fetching JP chart data.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadStockBySymbol(initialSymbol, timeframe);
  }, [initialSymbol, loadStockBySymbol, refreshNonce, timeframe]);

  if (!initialSymbol) {
    return watchlistRankingPanel ? (
      <section className="min-w-0">{watchlistRankingPanel}</section>
    ) : (
      <section className="border border-omi-border-subtle bg-omi-surface px-5 py-10 text-sm text-omi-text-muted">
        <div className="max-w-xl">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("jpMarket.sections.stock")}
          </div>
          <h2 className="mt-2 text-2xl font-bold text-omi-text-strong">
            {t("jpMarket.empty.noStockSelected")}
          </h2>
        <p className="mt-2 text-sm text-omi-text-muted">
          {t("jpMarket.empty.selectStockPrompt")}
        </p>
      </div>
      </section>
    );
  }

  return (
    <section
      className={[
        "grid w-full grid-cols-1 items-start justify-start gap-4",
        chartFocusMode ? "" : "xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className={["min-w-0 self-start", chartFocusMode ? "space-y-0" : "space-y-4"].join(" ")}>
        {chartFocusMode ? (
          <ProfessionalChartPanel
            title={selectedTitle}
            priceSummary={
              <div className={`flex items-baseline gap-2 ${priceToneClass(pct)}`}>
                <PriceUpdatePulse
                  value={latest?.close ?? null}
                  direction={change}
                  resetKey={`${selectedChartSymbol ?? "empty"}:jp-professional:${professionalTimeframe}`}
                  className="text-2xl font-bold leading-none tracking-normal tabular-nums"
                >
                  {formatNumber(latest?.close, 2)}
                </PriceUpdatePulse>
                <span className="text-sm font-semibold tabular-nums">
                  {formatSignedNumber(change)}
                </span>
                <span className="text-sm font-semibold tabular-nums">
                  ({formatSignedPct(pct)})
                </span>
              </div>
            }
            timeframeOptions={professionalTimeframeOptions.map((option) => ({
              key: option,
              label: timeframeLabel(t, option),
            }))}
            timeframe={professionalTimeframe}
            onTimeframeChange={handleProfessionalTimeframeChange}
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
                includeParameters
                parameters={indicatorParameters}
                onUpdateParameter={handleIndicatorParameterChange}
              />
            }
            onClose={() => {
              setIndicatorMenuOpen(false);
              setChartDrawingTool("cursor");
              setChartFocusMode(false);
            }}
            message={null}
            chartReady={professionalChartReady}
            emptyState={
              <div className="flex h-[640px] items-center justify-center border-t border-omi-border-subtle text-sm text-omi-text-muted">
                {chartLoading
                  ? t("common.loading")
                  : t("chart.loadingKline", { label: professionalTimeframeLabel })}
              </div>
            }
            chartData={chartData}
            label={professionalTimeframeLabel}
            timeMode="date"
            showMovingAverages={chartIndicators.ma}
            indicators={chartIndicators}
            indicatorParameters={indicatorParameters}
            volumePanelLabel={t("jpMarket.metrics.volume")}
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
          <>
        <section className="border border-omi-border-subtle bg-omi-surface">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 px-5 py-4">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("jpMarket.sections.stock")}
              </div>
              <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
                {selectedTitle}
              </h2>
              <div className="mt-1 text-sm text-omi-text-muted">
                {selectedSubtitle}
              </div>
            </div>

            <div className="shrink-0 text-right">
              <PriceUpdatePulse
                value={latest?.close ?? null}
                direction={change}
                resetKey={`${selectedStock?.symbol ?? initialSymbol}:${timeframe}`}
                className="text-3xl font-black text-omi-text-strong"
              >
                {formatNumber(latest?.close, 2)}
              </PriceUpdatePulse>
              <div className={`text-sm font-bold ${priceToneClass(pct)}`}>
                {formatSignedNumber(change)} / {formatSignedPct(pct)}
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
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setIndicatorMenuOpen((value) => !value)}
                    className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                  >
                    {t("stockDetail.indicators")}
                  </button>
                  {indicatorMenuOpen ? (
                    <TechnicalIndicatorMenu
                      indicators={chartIndicators}
                      activeTemplate={activeIndicatorTemplate}
                      onApplyTemplate={applyIndicatorTemplate}
                      onToggleIndicator={toggleChartIndicator}
                      includeParameters
                      parameters={indicatorParameters}
                      onUpdateParameter={handleIndicatorParameterChange}
                    />
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={enterChartFocusMode}
                  className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                >
                  {t("stockDetail.expand")}
                </button>
              </div>
            </div>
          </div>

          {chartData.length > 0 ? (
            <StockKLineChart
              chartData={chartData}
              label={selectedStock?.symbol ?? initialSymbol}
              indicators={chartIndicators}
              indicatorParameters={indicatorParameters}
              revealKey={`${selectedStock?.symbol ?? initialSymbol}-${timeframe}-${chartData.length}`}
              volumePanelLabel={t("jpMarket.metrics.volume")}
              volumeTooltipLabel={t("jpMarket.metrics.volume")}
              volumeValueFormatter={formatVolume}
            />
          ) : (
            <div className="flex h-[460px] items-center justify-center border-t border-omi-border-subtle text-sm text-omi-text-muted">
              {chartLoading ? t("common.loading") : t("jpMarket.empty.noKline")}
            </div>
          )}
        </section>

        {watchlistRankingPanel ? (
          <div className="min-w-0">{watchlistRankingPanel}</div>
        ) : null}
          </>
        )}
      </div>

      {!chartFocusMode ? (
      <aside className="flex min-w-0 flex-col border border-omi-border-subtle bg-omi-surface">
        <section>
          <div className="flex items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("jpMarket.sections.technical")}
              </div>
              <h3 className="mt-1 text-xl font-bold text-omi-text-strong">
                {t("jpMarket.technical.title")}
              </h3>
              <div className="mt-1 text-sm text-omi-text-muted">
                {t("jpMarket.technical.subtitle")}
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

        <div className="h-2 border-y border-omi-border-subtle bg-omi-surface-muted" aria-hidden="true" />

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
      </aside>
      ) : null}
    </section>
  );
}

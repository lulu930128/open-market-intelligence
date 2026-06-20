"use client";

import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import ResourceSlotTabs from "@/components/market-detail/ResourceSlotTabs";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import type {
  MarketDataSlotKey,
  ResourceSlotTabItem,
} from "@/components/market-detail/types";
import { timeframeLabel, useT } from "@/i18n";
import { fetchJson, requestJson } from "@/lib/api";
import type {
  ChartPoint,
  JPDailyPriceRefreshResultRead,
  JPOhlcChartRead,
  JPOhlcPointRead,
  JPResourceSummaryRead,
  JPStockMasterRead,
  JPStockMasterSyncResultRead,
} from "@/types/market";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type Message = { type: "success" | "error"; text: string } | null;
type JPChartTimeframe = "daily" | "weekly" | "monthly";
type JPDataSlot = Extract<
  MarketDataSlotKey,
  "chips" | "institutional" | "branch" | "revenue" | "earnings"
>;

type Props = {
  initialSymbol: string | null;
  onSelectStock: (stock: JPStockMasterRead | null) => void;
};

const timeframeOptions: JPChartTimeframe[] = ["daily", "weekly", "monthly"];
const barsByTimeframe: Record<JPChartTimeframe, number> = {
  daily: 180,
  weekly: 104,
  monthly: 72,
};
const jpDataSlots: Array<{ key: JPDataSlot; titleKey: string; descriptionKey: string }> = [
  {
    key: "chips",
    titleKey: "jpMarket.dataSlots.chips.title",
    descriptionKey: "jpMarket.dataSlots.chips.description",
  },
  {
    key: "institutional",
    titleKey: "jpMarket.dataSlots.institutional.title",
    descriptionKey: "jpMarket.dataSlots.institutional.description",
  },
  {
    key: "branch",
    titleKey: "jpMarket.dataSlots.branch.title",
    descriptionKey: "jpMarket.dataSlots.branch.description",
  },
  {
    key: "revenue",
    titleKey: "jpMarket.dataSlots.revenue.title",
    descriptionKey: "jpMarket.dataSlots.revenue.description",
  },
  {
    key: "earnings",
    titleKey: "jpMarket.dataSlots.earnings.title",
    descriptionKey: "jpMarket.dataSlots.earnings.description",
  },
];

const jpChartIndicators: IndicatorSettings = {
  ...defaultIndicators,
  ma: true,
  volume: true,
  signals: false,
};

function apiErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
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

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
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

function priceToneClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "text-omi-text-muted";
  if (value > 0) return "text-omi-danger";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text-muted";
}

function resourceStatusClass(status: string | null | undefined) {
  if (status === "available") return "text-omi-market-down";
  if (status === "empty") return "text-omi-warning";
  if (status === "loading") return "text-omi-accent";
  return "text-omi-text-muted";
}

function resourceStatusLabelKey(status: string | null | undefined) {
  if (status === "available") return "jpMarket.dataSlots.statusLabels.available";
  if (status === "empty") return "jpMarket.dataSlots.statusLabels.empty";
  if (status === "loading") return "jpMarket.dataSlots.statusLabels.loading";
  return "jpMarket.dataSlots.statusLabels.planned";
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

function messageClass(message: Message) {
  if (!message) return "";
  return message.type === "success"
    ? "border-omi-market-down-border bg-omi-market-down-soft text-omi-market-down"
    : "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
}

export default function JPMarketPanel({ initialSymbol, onSelectStock }: Props) {
  const t = useT();
  const onSelectStockRef = useRef(onSelectStock);
  const [selectedStock, setSelectedStock] = useState<JPStockMasterRead | null>(null);
  const [chart, setChart] = useState<JPOhlcChartRead | null>(null);
  const [resourceSummary, setResourceSummary] = useState<JPResourceSummaryRead | null>(null);
  const [timeframe, setTimeframe] = useState<JPChartTimeframe>("daily");
  const [activeDataSlot, setActiveDataSlot] = useState<JPDataSlot>("chips");
  const [stockState, setStockState] = useState<LoadState>("idle");
  const [dataState, setDataState] = useState<LoadState>("idle");
  const [syncState, setSyncState] = useState<LoadState>("idle");
  const [refreshState, setRefreshState] = useState<LoadState>("idle");
  const [message, setMessage] = useState<Message>(null);

  const chartData = useMemo<ChartPoint[]>(
    () => chart?.points.map(toChartPoint) ?? [],
    [chart]
  );
  const latest = latestPoint(chartData);
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
  const dailyPriceResource = useMemo(
    () => resourceSummary?.slots.find((slot) => slot.key === "daily_price") ?? null,
    [resourceSummary]
  );
  const dailyPriceStatus = dataState === "loading"
    ? "loading"
    : dailyPriceResource?.status ?? "empty";
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

  useEffect(() => {
    onSelectStockRef.current = onSelectStock;
  }, [onSelectStock]);

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

  const loadStockData = useCallback(
    async (symbol: string, nextTimeframe: JPChartTimeframe) => {
      setDataState("loading");

      try {
        const [chartResult, resourceResult] = await Promise.allSettled([
          fetchJson<JPOhlcChartRead>(
            `/api/jp-market/ohlc/${encodeURIComponent(symbol)}`,
            {
              timeframe: nextTimeframe,
              bars: barsByTimeframe[nextTimeframe],
              ensure_history: false,
            }
          ),
          fetchJson<JPResourceSummaryRead>(
            `/api/jp-market/resources/${encodeURIComponent(symbol)}/summary`
          ),
        ]);

        if (chartResult.status === "rejected") {
          throw chartResult.reason;
        }

        setChart(chartResult.value);
        setResourceSummary(resourceResult.status === "fulfilled" ? resourceResult.value : null);
        setDataState("success");
      } catch (error) {
        setChart(null);
        setResourceSummary(null);
        setDataState("error");
        setMessage({
          type: "error",
          text: apiErrorMessage(error, t("jpMarket.errors.dataLoadFailed")),
        });
      }
    },
    [t]
  );

  const loadStockBySymbol = useCallback(
    async (symbol: string, nextTimeframe: JPChartTimeframe) => {
      const normalizedSymbol = normalizeSymbolInput(symbol);
      if (!normalizedSymbol) return;

      setStockState("loading");
      setMessage(null);

      try {
        const stock = await fetchJson<JPStockMasterRead>(
          `/api/jp-market/stocks/${encodeURIComponent(normalizedSymbol)}`
        );

        setSelectedStock(stock);
        setStockState("success");
        onSelectStockRef.current(stock);
        await loadStockData(stock.symbol, nextTimeframe);
      } catch (error) {
        setSelectedStock(null);
        setChart(null);
        setResourceSummary(null);
        setStockState("error");
        setDataState("idle");
        onSelectStockRef.current(null);
        setMessage({
          type: "error",
          text: apiErrorMessage(error, t("jpMarket.errors.masterLoadFailed")),
        });
      }
    },
    [loadStockData, t]
  );

  useEffect(() => {
    if (!initialSymbol) {
      return;
    }

    // Symbol/timeframe changes are the external signal for fetching JP chart data.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadStockBySymbol(initialSymbol, timeframe);
  }, [initialSymbol, loadStockBySymbol, timeframe]);

  async function syncMaster() {
    setSyncState("loading");
    setMessage(null);

    try {
      const result = await requestJson<JPStockMasterSyncResultRead>(
        "/api/jp-market/stocks/sync-symbols",
        { method: "POST" },
        { deactivate_missing: false }
      );

      setSyncState("success");
      setMessage({
        type: "success",
        text: t("jpMarket.messages.syncSuccess", {
          scanned: result.scanned_count,
          created: result.created_count,
          updated: result.updated_count,
        }),
      });

      if (initialSymbol) {
        await loadStockBySymbol(initialSymbol, timeframe);
      }
    } catch (error) {
      setSyncState("error");
      setMessage({
        type: "error",
        text: apiErrorMessage(error, t("jpMarket.errors.syncFailed")),
      });
    }
  }

  async function refreshDaily() {
    if (!selectedStock) return;

    setRefreshState("loading");
    setMessage(null);

    try {
      const result = await requestJson<JPDailyPriceRefreshResultRead>(
        `/api/jp-market/daily/${encodeURIComponent(selectedStock.symbol)}/refresh`,
        { method: "POST" },
        {
          outputsize: timeframe === "daily" ? "compact" : "full",
          provider: "auto",
        }
      );

      setRefreshState("success");
      setMessage({
        type: "success",
        text: t("jpMarket.messages.dailyRefreshSuccess", {
          symbol: result.symbol,
          fetched: result.fetched_count,
          inserted: result.inserted_count,
          updated: result.updated_count,
        }),
      });
      await loadStockData(selectedStock.symbol, timeframe);
    } catch (error) {
      setRefreshState("error");
      setMessage({
        type: "error",
        text: apiErrorMessage(error, t("jpMarket.errors.dailyRefreshFailed")),
      });
    }
  }

  if (!initialSymbol) {
    return (
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
          <button
            type="button"
            className="mt-5 h-9 border border-omi-border bg-omi-surface-subtle px-4 text-sm font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:border-omi-border-subtle disabled:text-omi-text-subtle"
            onClick={() => void syncMaster()}
            disabled={syncState === "loading"}
          >
            {syncState === "loading"
              ? t("jpMarket.actions.syncing")
              : t("jpMarket.actions.syncMaster")}
          </button>
        </div>

        {message ? (
          <div className={`mt-5 border px-3 py-2 text-xs ${messageClass(message)}`}>
            {message.text}
          </div>
        ) : null}
      </section>
    );
  }

  return (
    <section className="grid w-full grid-cols-1 items-start justify-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]">
      <div className="min-w-0 space-y-4 self-start">
        <section className="border border-omi-border-subtle bg-omi-surface">
          <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
            <div>
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

            <div className="text-right">
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
              <div className="mt-3 flex flex-wrap justify-end gap-2">
                {timeframeOptions.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setTimeframe(option)}
                    className={[
                      "h-8 border px-3 text-sm font-semibold",
                      timeframe === option
                        ? "border-omi-accent bg-omi-accent text-omi-text-inverse"
                        : "border-omi-border-subtle bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
                    ].join(" ")}
                  >
                    {timeframeLabel(t, option)}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {message ? (
            <div className={`border-t px-5 py-3 text-sm ${messageClass(message)}`}>
              {message.text}
            </div>
          ) : null}

          <div className="grid grid-cols-2 border-t border-omi-border-subtle md:grid-cols-3 2xl:grid-cols-6">
            {headerMetrics.map((item, index) => (
              <div
                key={item.label}
                className={[
                  "px-5 py-3",
                  index % 2 === 1 ? "border-l border-omi-border-subtle" : "",
                  index >= 2 ? "border-t border-omi-border-subtle md:border-t-0" : "",
                  index > 0 ? "md:border-l md:border-omi-border-subtle" : "",
                ].join(" ")}
              >
                <div className="text-xs text-omi-text-muted">{item.label}</div>
                <div className="mt-1 break-words text-sm font-bold">{item.value}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="border border-omi-border-subtle bg-omi-surface">
          <div className="flex items-center justify-between border-b border-omi-border-subtle px-5 py-3">
            <div>
              <h3 className="text-sm font-bold text-omi-text-strong">
                {t("stockDetail.chartIndicators")}
              </h3>
              <div className="mt-1 text-xs text-omi-text-muted">
                {timeframeLabel(t, timeframe)} · {chart?.point_count ?? 0}{" "}
                {t("stockDetail.points")} · {t("jpMarket.dataSlots.dailyPrice")}{" "}
                <span className={resourceStatusClass(dailyPriceStatus)}>
                  {t(resourceStatusLabelKey(dailyPriceStatus))}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void syncMaster()}
                className="h-8 border border-omi-control bg-omi-surface px-3 text-xs font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                disabled={syncState === "loading"}
              >
                {syncState === "loading"
                  ? t("jpMarket.actions.syncing")
                  : t("jpMarket.actions.syncMaster")}
              </button>
              <button
                type="button"
                onClick={() => void refreshDaily()}
                className="h-8 bg-omi-control px-3 text-xs font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-border"
                disabled={!selectedStock || refreshState === "loading"}
              >
                {refreshState === "loading"
                  ? t("common.updating")
                  : t("jpMarket.actions.refreshDaily")}
              </button>
            </div>
          </div>

          {chartData.length > 0 ? (
            <StockKLineChart
              chartData={chartData}
              label={selectedStock?.symbol ?? initialSymbol}
              indicators={jpChartIndicators}
              indicatorParameters={defaultIndicatorParameters}
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

      </div>

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

        <ResourceSlotTabs
          activeKey={activeDataSlot}
          labels={resourceSlotLabels}
          onActiveKeyChange={setActiveDataSlot}
          slots={resourceSlotItems}
          statusLabel={(status) => t(resourceStatusLabelKey(status))}
          statusToneClass={resourceStatusClass}
          footer={
            <div className="grid grid-cols-2 gap-px bg-omi-border-subtle">
              {headerMetrics.map((item) => (
                <MetricCell key={item.label} label={item.label} value={item.value} />
              ))}
            </div>
          }
        />
      </aside>
    </section>
  );
}

"use client";

import IntradayTrendChart from "@/components/IntradayTrendChart";
import StockKLineChart, {
  defaultIndicators,
  indicatorOptions,
  type IndicatorKey,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import { fetchJson } from "@/lib/api";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  getTaiwanMarketRefreshState,
} from "@/lib/taiwanMarketTime";
import type {
  ChartPoint,
  IntradayTrendPoint,
  IntradayTrendResponse,
  InstitutionalTradeDailyRead,
  MarginTradingDailyRead,
  OhlcChartResponse,
  StockIndicatorPoint,
  StockMasterRead,
} from "@/types/market";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

type Props = {
  stockId: string | null;
  stockName: string | null;
  initialChartData?: ChartPoint[];
  initialIndicatorData?: StockIndicatorPoint[];
  watchlistRankingPanel?: ReactNode;
};

type Timeframe = "today" | "daily" | "weekly" | "monthly";
type LoadState = "idle" | "loading" | "success" | "error";

const timeframeLabels: Record<Timeframe, string> = {
  today: "今日",
  daily: "日K",
  weekly: "週K",
  monthly: "月K",
};

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value));
}

function formatSignedNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value)}`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatDateTime(value: string | null | undefined) {
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
    timeZone: "Asia/Taipei",
  }).format(date);
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-slate-500";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
}

function safeRatio(numerator: number | null | undefined, denominator: number | null | undefined) {
  if (
    numerator === null ||
    numerator === undefined ||
    denominator === null ||
    denominator === undefined ||
    denominator === 0
  ) {
    return null;
  }

  return numerator / denominator;
}

async function fetchOptional<T>(path: string): Promise<T | null> {
  try {
    return await fetchJson<T>(path);
  } catch {
    return null;
  }
}

function TechnicalBar({ label, value }: { label: string; value: number | null }) {
  const displayValue = value === null ? 0 : Math.max(-12, Math.min(12, value));
  const width = `${Math.abs(displayValue / 12) * 50}%`;
  const isPositive = displayValue >= 0;

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className={valueTone(value)}>{value === null ? "-" : formatPct(value)}</span>
      </div>
      <div className="relative h-2 bg-slate-100">
        <div className="absolute left-1/2 top-0 h-2 w-px bg-slate-300" />
        <div
          className={[
            "absolute top-0 h-2",
            isPositive ? "left-1/2 bg-red-500" : "right-1/2 bg-emerald-500",
          ].join(" ")}
          style={{ width }}
        />
      </div>
    </div>
  );
}

function MetricRow({
  label,
  value,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-slate-100 py-2 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className={`font-semibold ${tone}`}>{value}</span>
    </div>
  );
}

function ChipMetricBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs font-bold text-slate-900">{title}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

export default function StockDetailPanel({
  stockId,
  stockName,
  initialChartData = [],
  initialIndicatorData = [],
  watchlistRankingPanel,
}: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("daily");
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [chartIndicators, setChartIndicators] =
    useState<IndicatorSettings>(defaultIndicators);
  const [chartData, setChartData] = useState<ChartPoint[]>(initialChartData);
  const [todayTrend, setTodayTrend] = useState<IntradayTrendPoint[]>([]);
  const [todayPreviousClose, setTodayPreviousClose] = useState<number | null>(null);
  const [todaySource, setTodaySource] = useState("unavailable");
  const [todayUpdatedAt, setTodayUpdatedAt] = useState<string | null>(null);
  const [indicatorData, setIndicatorData] =
    useState<StockIndicatorPoint[]>(initialIndicatorData);
  const [institutional, setInstitutional] = useState<InstitutionalTradeDailyRead | null>(null);
  const [margin, setMargin] = useState<MarginTradingDailyRead | null>(null);
  const [stockInfo, setStockInfo] = useState<StockMasterRead | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const finalIntradayRefreshDate = useRef<string | null>(null);

  function toggleChartIndicator(key: IndicatorKey) {
    setChartIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  useEffect(() => {
    if (!stockId) {
      const timer = window.setTimeout(() => {
        setChartData([]);
        setTodayTrend([]);
        setTodayPreviousClose(null);
        setTodaySource("unavailable");
        setTodayUpdatedAt(null);
        setIndicatorData([]);
        setInstitutional(null);
        setMargin(null);
        setStockInfo(null);
        setLoadState("idle");
        setErrorMessage(null);
      }, 0);

      return () => window.clearTimeout(timer);
    }

    let cancelled = false;

    async function loadStaticDetail() {
      try {
        const [institutionalData, marginData, stockData] = await Promise.all([
          fetchOptional<InstitutionalTradeDailyRead>(
            `/api/market/institutional/${stockId}/latest`
          ),
          fetchOptional<MarginTradingDailyRead>(`/api/market/margin/${stockId}/latest`),
          fetchOptional<StockMasterRead>(`/api/stocks/${stockId}`),
        ]);

        if (cancelled) return;

        setInstitutional(institutionalData);
        setMargin(marginData);
        setStockInfo(stockData);
      } catch {
        if (!cancelled) {
          setInstitutional(null);
          setMargin(null);
          setStockInfo(null);
        }
      }
    }

    void loadStaticDetail();

    return () => {
      cancelled = true;
    };
  }, [stockId]);

  useEffect(() => {
    if (!stockId) return;

    let cancelled = false;
    let intradayTimer: number | undefined;
    let intradayRequestInFlight = false;

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
        setLoadState("loading");
        setErrorMessage(null);
        setTodayUpdatedAt(null);
      }

      try {
        const today = await fetchJson<IntradayTrendResponse>(
          `/api/market/intraday/${stockId}`
        );

        if (cancelled) return;

        setTodayTrend(today.points);
        setTodayPreviousClose(today.previous_close);
        setTodaySource(today.source);
        const latestPoint = today.points[today.points.length - 1] ?? null;
        setTodayUpdatedAt(latestPoint ? formatDateTime(latestPoint.time) : null);
        setLoadState("success");
        setErrorMessage(null);
      } catch (error) {
        if (cancelled) return;
        setLoadState("error");
        setErrorMessage(error instanceof Error ? error.message : "資料讀取失敗");
      } finally {
        intradayRequestInFlight = false;
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
        finalIntradayRefreshDate.current !== marketState.dateKey
      ) {
        finalIntradayRefreshDate.current = marketState.dateKey;
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
      if (timeframe === "today") {
        await loadTodayTrend(true);

        if (!cancelled) {
          const marketState = getTaiwanMarketRefreshState();

          if (marketState.isAfterClose) {
            finalIntradayRefreshDate.current = marketState.dateKey;
          }

          scheduleTodayRefresh();
        }

        return;
      }

      setLoadState("loading");
      setErrorMessage(null);

      try {
        const ohlc = await fetchJson<OhlcChartResponse>(`/api/market/ohlc/${stockId}`, {
          timeframe,
          bars: 90,
          ensure_history: true,
        });
        const indicators = await fetchJson<StockIndicatorPoint[]>(
          `/api/market/indicators/${stockId}/daily`,
          {
            limit: 520,
            ma_windows: "5,20,60",
            volume_ma_windows: "5,20",
          }
        );

        if (cancelled) return;

        setChartData(ohlc.points);
        setIndicatorData(indicators);
        setLoadState("success");
      } catch (error) {
        if (cancelled) return;
        setLoadState("error");
        setErrorMessage(error instanceof Error ? error.message : "資料讀取失敗");
      }
    }

    void loadChart();

    return () => {
      cancelled = true;
      clearIntradayTimer();
    };
  }, [stockId, timeframe]);

  const indicatorForTimeframe = useMemo(() => {
    if (timeframe === "daily") return indicatorData.slice(-180);
    return [];
  }, [indicatorData, timeframe]);

  const latestIndicator = indicatorData[indicatorData.length - 1] ?? null;
  const latestChart = chartData[chartData.length - 1] ?? null;
  const latestToday = todayTrend[todayTrend.length - 1] ?? null;
  const latestClose =
    timeframe === "today"
      ? latestToday?.price ?? latestIndicator?.close ?? latestChart?.close ?? null
      : latestIndicator?.close ?? latestChart?.close ?? null;
  const latestChangePct =
    timeframe === "today" && latestToday && todayPreviousClose
      ? ((latestToday.price - todayPreviousClose) / todayPreviousClose) * 100
      : latestIndicator?.change_pct ?? null;
  const ma5 = latestIndicator?.ma?.ma5 ?? null;
  const ma20 = latestIndicator?.ma?.ma20 ?? null;
  const ma60 = latestIndicator?.ma?.ma60 ?? null;
  const volumeMa20 = latestIndicator?.volume_ma?.volume_ma20 ?? null;
  const priceVsMa20 =
    latestClose !== null && ma20 !== null && ma20 !== 0
      ? ((latestClose - ma20) / ma20) * 100
      : null;
  const volumeRatio = safeRatio(latestIndicator?.volume, volumeMa20);
  const volumeRatioPct = volumeRatio === null ? null : (volumeRatio - 1) * 100;
  const totalInstitutionalNet = institutional?.total_institutional_net ?? null;
  const displayTime =
    timeframe === "today" && latestToday
      ? formatDateTime(latestToday.time)
      : latestIndicator?.time ?? latestChart?.time ?? "-";

  const technicalStatus = useMemo(() => {
    if (latestClose === null) return "資料不足";
    if (ma20 !== null && ma60 !== null && latestClose > ma20 && ma20 > ma60) {
      return "多方排列";
    }
    if (ma20 !== null && ma60 !== null && latestClose < ma20 && ma20 < ma60) {
      return "空方排列";
    }
    if (ma20 !== null && latestClose > ma20) return "偏多整理";
    if (ma20 !== null && latestClose < ma20) return "偏弱整理";
    return "中性";
  }, [latestClose, ma20, ma60]);

  const signals = useMemo(() => {
    const result: { label: string; tone: string }[] = [];

    if (latestClose !== null && ma20 !== null) {
      result.push({
        label: latestClose >= ma20 ? "收盤站上 MA20" : "收盤跌破 MA20",
        tone: latestClose >= ma20 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50",
      });
    }

    if (ma5 !== null && ma20 !== null) {
      result.push({
        label: ma5 >= ma20 ? "短均線偏多" : "短均線偏弱",
        tone: ma5 >= ma20 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50",
      });
    }

    if (volumeRatio !== null) {
      result.push({
        label: volumeRatio >= 1.5 ? "量能放大" : "量能一般",
        tone: volumeRatio >= 1.5 ? "text-amber-700 bg-amber-50" : "text-slate-600 bg-slate-100",
      });
    }

    if (totalInstitutionalNet !== null) {
      result.push({
        label: totalInstitutionalNet >= 0 ? "法人買超" : "法人賣超",
        tone:
          totalInstitutionalNet >= 0
            ? "text-red-700 bg-red-50"
            : "text-emerald-700 bg-emerald-50",
      });
    }

    return result;
  }, [latestClose, ma5, ma20, totalInstitutionalNet, volumeRatio]);

  const chipDateGroups = useMemo(() => {
    const groups = new Map<
      string,
      {
        tradeDate: string;
        institutional: InstitutionalTradeDailyRead | null;
        margin: MarginTradingDailyRead | null;
      }
    >();

    if (institutional?.trade_date) {
      groups.set(institutional.trade_date, {
        tradeDate: institutional.trade_date,
        institutional,
        margin: null,
      });
    }

    if (margin?.trade_date) {
      const current = groups.get(margin.trade_date);

      groups.set(margin.trade_date, {
        tradeDate: margin.trade_date,
        institutional: current?.institutional ?? null,
        margin,
      });
    }

    return Array.from(groups.values()).sort((a, b) =>
      b.tradeDate.localeCompare(a.tradeDate)
    );
  }, [institutional, margin]);

  if (!stockId) {
    return watchlistRankingPanel ? (
      <section className="min-w-0">{watchlistRankingPanel}</section>
    ) : null;
  }

  const technicalSpanClass = watchlistRankingPanel ? "xl:row-span-2" : "";

  return (
    <section className="grid w-full grid-cols-1 justify-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]">
      <div className="min-w-0 border border-slate-200 bg-white">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                Stock
              </div>
              <h2 className="mt-1 text-2xl font-bold text-slate-950">
                {stockId} {stockName ?? stockInfo?.stock_name ?? ""}
              </h2>
              <div className="mt-1 text-sm text-slate-500">
                {stockInfo?.market ?? "-"} · {stockInfo?.industry ?? "未分類"} ·{" "}
                {displayTime}
              </div>
            </div>

            <div className="flex items-start gap-5">
              <div className="text-right">
                <div className="text-3xl font-bold text-slate-950">
                  {formatPrice(latestClose)}
                </div>
                <div className={`mt-1 text-sm font-semibold ${valueTone(latestChangePct)}`}>
                  {formatPct(latestChangePct)}
                </div>
              </div>

              <div className="flex flex-col items-end gap-2">
                <div className="flex border border-slate-200 bg-slate-50 p-1">
                  {(Object.keys(timeframeLabels) as Timeframe[]).map((item) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => setTimeframe(item)}
                      className={[
                        "h-8 min-w-12 px-3 text-sm font-semibold transition",
                        timeframe === item
                          ? "bg-red-700 text-white"
                          : "text-slate-600 hover:bg-white",
                      ].join(" ")}
                    >
                      {timeframeLabels[item]}
                    </button>
                  ))}
                </div>

                {timeframe !== "today" ? (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className="h-8 border border-slate-900 bg-white px-3 text-sm font-semibold text-slate-900 hover:border-red-700 hover:text-red-700"
                    >
                      指標
                    </button>
                    {indicatorMenuOpen ? (
                      <div className="absolute right-0 z-20 mt-2 w-48 border border-slate-200 bg-white p-2 text-left shadow-lg">
                        {indicatorOptions.map((option) => (
                          <label
                            key={option.key}
                            className="flex cursor-pointer items-start gap-2 px-2 py-2 text-xs hover:bg-slate-50"
                          >
                            <input
                              type="checkbox"
                              checked={chartIndicators[option.key]}
                              onChange={() => toggleChartIndicator(option.key)}
                              className="mt-0.5"
                            />
                            <span>
                              <span className="block font-semibold text-slate-800">
                                {option.label}
                              </span>
                              <span className="block text-slate-500">
                                {option.description}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {errorMessage ? (
            <div className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700">
              {errorMessage}
            </div>
          ) : null}

          {timeframe === "today" ? (
            <IntradayTrendChart
              points={todayTrend}
              previousClose={todayPreviousClose}
              label={timeframeLabels[timeframe]}
              source={todaySource}
              refreshIntervalMs={TAIWAN_INTRADAY_REFRESH_MS}
              updatedAt={todayUpdatedAt}
            />
          ) : (
            <StockKLineChart
              chartData={chartData}
              indicatorData={indicatorForTimeframe}
              label={timeframeLabels[timeframe]}
              indicators={chartIndicators}
            />
          )}
        </div>

      <aside
        className={`flex min-w-0 flex-col border border-slate-200 bg-white ${technicalSpanClass}`}
      >
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Technical
            </div>
            <div className="mt-2 flex items-end justify-between gap-4">
              <div>
                <div className="text-xl font-bold text-slate-950">{technicalStatus}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {loadState === "loading" ? "讀取中" : "均線、量能、法人綜合判讀"}
                </div>
              </div>
              <div className={`text-right text-lg font-bold ${valueTone(priceVsMa20)}`}>
                {formatPct(priceVsMa20)}
                <div className="text-xs font-medium text-slate-500">vs MA20</div>
              </div>
            </div>
          </div>

          <div className="space-y-4 px-5 py-4">
            <TechnicalBar label="價格相對 MA20" value={priceVsMa20} />
            <TechnicalBar label="量能相對 20 日均量" value={volumeRatioPct} />
            <TechnicalBar
              label="三大法人淨買賣"
              value={
                totalInstitutionalNet === null
                  ? null
                  : Math.max(-12, Math.min(12, totalInstitutionalNet / 1_000_000))
              }
            />

            <div className="grid grid-cols-3 border border-slate-200 text-center text-xs">
              <div className="px-2 py-3">
                <div className="text-slate-500">MA5</div>
                <div className="mt-1 font-semibold text-slate-900">{formatPrice(ma5)}</div>
              </div>
              <div className="border-x border-slate-200 px-2 py-3">
                <div className="text-slate-500">MA20</div>
                <div className="mt-1 font-semibold text-slate-900">{formatPrice(ma20)}</div>
              </div>
              <div className="px-2 py-3">
                <div className="text-slate-500">MA60</div>
                <div className="mt-1 font-semibold text-slate-900">{formatPrice(ma60)}</div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {signals.map((signal) => (
                <span key={signal.label} className={`px-2.5 py-1 text-xs font-semibold ${signal.tone}`}>
                  {signal.label}
                </span>
              ))}
            </div>
          </div>

          <div className="border-t border-slate-200 px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Data
            </div>
            <div className="mt-1 flex items-end justify-between gap-4">
              <div>
                <div className="text-lg font-bold text-slate-950">籌碼資料</div>
                <div className="mt-1 text-xs text-slate-500">依資料日期分類</div>
              </div>
            </div>

            <div className="mt-4 space-y-4">
              {chipDateGroups.length ? (
                chipDateGroups.map((group) => (
                  <div key={group.tradeDate} className="space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                        Date
                      </span>
                      <span className="text-sm font-bold text-slate-900">
                        {group.tradeDate}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
                      <ChipMetricBlock title="三大法人">
                        <MetricRow
                          label="外資買賣超"
                          value={formatSignedNumber(group.institutional?.foreign_investor_net)}
                          tone={valueTone(group.institutional?.foreign_investor_net)}
                        />
                        <MetricRow
                          label="投信買賣超"
                          value={formatSignedNumber(group.institutional?.investment_trust_net)}
                          tone={valueTone(group.institutional?.investment_trust_net)}
                        />
                        <MetricRow
                          label="自營商買賣超"
                          value={formatSignedNumber(group.institutional?.dealer_net)}
                          tone={valueTone(group.institutional?.dealer_net)}
                        />
                        <MetricRow
                          label="三大法人合計"
                          value={formatSignedNumber(group.institutional?.total_institutional_net)}
                          tone={valueTone(group.institutional?.total_institutional_net)}
                        />
                      </ChipMetricBlock>

                      <ChipMetricBlock title="融資融券">
                        <MetricRow
                          label="融資餘額"
                          value={formatNumber(group.margin?.margin_today_balance)}
                        />
                        <MetricRow
                          label="融券餘額"
                          value={formatNumber(group.margin?.short_today_balance)}
                        />
                        <MetricRow
                          label="資券相抵"
                          value={formatNumber(group.margin?.offset)}
                        />
                        <MetricRow
                          label="融資買 / 賣"
                          value={`${formatNumber(group.margin?.margin_buy)} / ${formatNumber(
                            group.margin?.margin_sell
                          )}`}
                        />
                      </ChipMetricBlock>
                    </div>
                  </div>
                ))
              ) : (
                <div className="border border-dashed border-slate-200 px-4 py-6 text-center text-sm text-slate-500">
                  尚無三大法人或融資融券資料
                </div>
              )}
            </div>
          </div>
      </aside>

      {watchlistRankingPanel ? <div className="min-w-0">{watchlistRankingPanel}</div> : null}
    </section>
  );
}

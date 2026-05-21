"use client";

import IntradayTrendChart from "@/components/IntradayTrendChart";
import StockKLineChart from "@/components/StockKLineChart";
import { fetchJson } from "@/lib/api";
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
import { type ReactNode, useEffect, useMemo, useState } from "react";

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

function DataCell({
  label,
  value,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="border-t border-slate-200 px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-1 text-sm font-semibold ${tone}`}>{value}</div>
    </div>
  );
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

export default function StockDetailPanel({
  stockId,
  stockName,
  initialChartData = [],
  initialIndicatorData = [],
  watchlistRankingPanel,
}: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("daily");
  const [chartData, setChartData] = useState<ChartPoint[]>(initialChartData);
  const [todayTrend, setTodayTrend] = useState<IntradayTrendPoint[]>([]);
  const [todayPreviousClose, setTodayPreviousClose] = useState<number | null>(null);
  const [todaySource, setTodaySource] = useState("unavailable");
  const [indicatorData, setIndicatorData] =
    useState<StockIndicatorPoint[]>(initialIndicatorData);
  const [institutional, setInstitutional] = useState<InstitutionalTradeDailyRead | null>(null);
  const [margin, setMargin] = useState<MarginTradingDailyRead | null>(null);
  const [stockInfo, setStockInfo] = useState<StockMasterRead | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!stockId) {
      const timer = window.setTimeout(() => {
        setChartData([]);
        setTodayTrend([]);
        setTodayPreviousClose(null);
        setTodaySource("unavailable");
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

    async function loadChart() {
      setLoadState("loading");
      setErrorMessage(null);

      try {
        if (timeframe === "today") {
          const today = await fetchJson<IntradayTrendResponse>(
            `/api/market/intraday/${stockId}`
          );

          if (cancelled) return;

          setTodayTrend(today.points);
          setTodayPreviousClose(today.previous_close);
          setTodaySource(today.source);
          setLoadState("success");
          return;
        }

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
  const foreignNet = institutional?.foreign_investor_net ?? null;
  const investmentTrustNet = institutional?.investment_trust_net ?? null;
  const dealerNet = institutional?.dealer_net ?? null;
  const totalInstitutionalNet = institutional?.total_institutional_net ?? null;

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

  if (!stockId) {
    return (
      <section className="space-y-4">
        <div className="flex min-h-[520px] items-center justify-center border border-slate-200 bg-white">
          <div className="max-w-md text-center">
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-400">
              Stock Detail
            </div>
            <h2 className="mt-3 text-2xl font-bold text-slate-950">選一檔股票開始</h2>
            <p className="mt-3 text-sm leading-6 text-slate-500">
              從左側自選股或下方排行點選股票，這裡會顯示 K 線、技術分析與籌碼資料。
            </p>
          </div>
        </div>
        {watchlistRankingPanel ? <div className="min-w-0">{watchlistRankingPanel}</div> : null}
      </section>
    );
  }

  const technicalSpanClass = watchlistRankingPanel ? "xl:row-span-3" : "xl:row-span-2";

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
                {latestIndicator?.time ?? latestChart?.time ?? "-"}
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
            />
          ) : (
            <StockKLineChart
              chartData={chartData}
              indicatorData={indicatorForTimeframe}
              label={timeframeLabels[timeframe]}
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
      </aside>

      <div className="min-w-0 border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-3">
          <h3 className="text-sm font-bold text-slate-950">資料摘要</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6">
          <DataCell label="成交量" value={formatNumber(latestIndicator?.volume ?? latestChart?.volume)} />
          <DataCell label="成交金額" value={formatNumber(latestChart?.trade_value)} />
          <DataCell label="外資買賣超" value={formatSignedNumber(foreignNet)} tone={valueTone(foreignNet)} />
          <DataCell
            label="投信買賣超"
            value={formatSignedNumber(investmentTrustNet)}
            tone={valueTone(investmentTrustNet)}
          />
          <DataCell label="自營商買賣超" value={formatSignedNumber(dealerNet)} tone={valueTone(dealerNet)} />
          <DataCell
            label="三大法人合計"
            value={formatSignedNumber(totalInstitutionalNet)}
            tone={valueTone(totalInstitutionalNet)}
          />
          <DataCell label="融資餘額" value={formatNumber(margin?.margin_today_balance)} />
          <DataCell label="融券餘額" value={formatNumber(margin?.short_today_balance)} />
          <DataCell label="資券相抵" value={formatNumber(margin?.offset)} />
          <DataCell label="市場" value={stockInfo?.market ?? "-"} />
          <DataCell label="產業" value={stockInfo?.industry ?? "-"} />
          <DataCell label="資料日期" value={latestIndicator?.time ?? latestChart?.time ?? "-"} />
        </div>
      </div>
      {watchlistRankingPanel ? <div className="min-w-0">{watchlistRankingPanel}</div> : null}
    </section>
  );
}

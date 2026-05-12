"use client";

import StockKLineChart from "@/components/StockKLineChart";
import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "@/lib/api";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";

type Props = {
  stockId: string | null;
  stockName: string | null;
};

type LoadState = "idle" | "loading" | "success" | "error";

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return new Intl.NumberFormat("zh-TW").format(value);
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function changeClass(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-slate-400";
  if (value > 0) return "text-rose-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-600";
}

export default function StockDetailPanel({ stockId, stockName }: Props) {
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [indicatorData, setIndicatorData] = useState<StockIndicatorPoint[]>([]);
  const [chartRange, setChartRange] = useState<"1M" | "3M" | "6M" | "ALL">("3M");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const latestIndicator = indicatorData[indicatorData.length - 1] ?? null;
  const latestChart = chartData[chartData.length - 1] ?? null;

  const recentStats = useMemo(() => {
    const recent = chartData.slice(-20);

    const highs = recent
      .map((point) => point.high)
      .filter((value): value is number => value !== null && value !== undefined);

    const lows = recent
      .map((point) => point.low)
      .filter((value): value is number => value !== null && value !== undefined);

    const volumes = recent
      .map((point) => point.volume)
      .filter((value): value is number => value !== null && value !== undefined);

    const averageVolume =
      volumes.length > 0
        ? volumes.reduce((sum, value) => sum + value, 0) / volumes.length
        : null;

    return {
      high20: highs.length > 0 ? Math.max(...highs) : null,
      low20: lows.length > 0 ? Math.min(...lows) : null,
      averageVolume20: averageVolume,
    };
  }, [chartData]);

  async function loadStockDetail(currentStockId: string) {
    setLoadState("loading");
    setErrorMessage(null);

    try {
      const [chart, indicators] = await Promise.all([
        fetchJson<ChartPoint[]>(`/api/market/daily/${currentStockId}/chart`, {
        limit: 260,
        }),
        fetchJson<StockIndicatorPoint[]>(
        `/api/market/indicators/${currentStockId}/daily`,
        {
            limit: 260,
            ma_windows: "5,20,60",
            volume_ma_windows: "5,20",
        }
        ),
      ]);

      setChartData(chart);
      setIndicatorData(indicators);
      setLoadState("success");
    } catch (error) {
      setLoadState("error");
      setErrorMessage(error instanceof Error ? error.message : "Unknown error");
    }
  }

  useEffect(() => {
    if (!stockId) {
      const timerId = window.setTimeout(() => {
        setChartData([]);
        setIndicatorData([]);
        setLoadState("idle");
        setErrorMessage(null);
      }, 0);

      return () => window.clearTimeout(timerId);
    }

    const timerId = window.setTimeout(() => {
      void loadStockDetail(stockId);
    }, 0);

    return () => window.clearTimeout(timerId);
  }, [stockId]);

  if (!stockId) {
    return (
      <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
        <h2 className="text-lg font-bold">Stock Detail</h2>
        <p className="mt-2 text-sm text-slate-500">
          點左側股票或 Ranking 表格中的股票後，這裡會顯示個股詳細資訊。
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-500">Stock Detail</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight">
            {stockId} {stockName ?? ""}
          </h2>
          <p className="mt-2 text-sm text-slate-500">
            {latestIndicator?.time ?? latestChart?.time ?? "-"} ·{" "}
            {loadState === "loading" ? "Loading..." : "latest daily data"}
          </p>
        </div>

        <div className="text-right">
          <div className="text-3xl font-bold">
            {formatPrice(latestIndicator?.close ?? latestChart?.close)}
          </div>
          <div
            className={[
              "mt-1 text-sm font-semibold",
              changeClass(latestIndicator?.change_pct),
            ].join(" ")}
          >
            {formatPct(latestIndicator?.change_pct)}
          </div>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-2">
            {(["1M", "3M", "6M", "ALL"] as const).map((range) => (
                <button
                key={range}
                type="button"
                onClick={() => setChartRange(range)}
                className={[
                    "rounded-xl px-3 py-1.5 text-xs font-semibold ring-1 transition",
                    chartRange === range
                    ? "bg-indigo-600 text-white ring-indigo-600"
                    : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50",
                ].join(" ")}
                >
                {range}
                </button>
            ))}

            <span className="text-xs text-slate-400">
                Range controls only affect the chart display.
            </span>
            </div>
      </div>

      {errorMessage ? (
        <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {errorMessage}
        </div>
      ) : null}

      {chartData.length > 0 && chartData.length < 20 ? (
        <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700">
          目前這檔股票的歷史資料偏少，建議在左側選取資料夾後執行 Backfill，讓 K 線與均線判斷更完整。
        </div>
      ) : null}

      <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-[1.4fr_1fr]">
        <StockKLineChart
          chartData={chartData}
          indicatorData={indicatorData}
          range={chartRange}
          />
          <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-2xl bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">MA5</p>
            <p className="mt-2 font-bold">{formatPrice(latestIndicator?.ma?.["ma5"])}</p>
          </div>

          <div className="rounded-2xl bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">MA20</p>
            <p className="mt-2 font-bold">{formatPrice(latestIndicator?.ma?.["ma20"])}</p>
          </div>

          <div className="rounded-2xl bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">20D High</p>
            <p className="mt-2 font-bold">{formatPrice(recentStats.high20)}</p>
          </div>

          <div className="rounded-2xl bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">20D Low</p>
            <p className="mt-2 font-bold">{formatPrice(recentStats.low20)}</p>
          </div>

          <div className="rounded-2xl bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">Volume</p>
            <p className="mt-2 font-bold">{formatNumber(latestIndicator?.volume)}</p>
          </div>

          <div className="rounded-2xl bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">20D Avg Vol</p>
            <p className="mt-2 font-bold">
              {formatNumber(recentStats.averageVolume20)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

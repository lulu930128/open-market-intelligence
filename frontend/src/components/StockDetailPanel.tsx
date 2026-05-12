"use client";

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

function Sparkline({ points }: { points: ChartPoint[] }) {
  const closes = points
    .map((point) => point.close)
    .filter((value): value is number => value !== null && value !== undefined);

  if (closes.length < 2) {
    return (
      <div className="flex h-28 items-center justify-center rounded-2xl bg-slate-50 text-sm text-slate-400">
        Not enough chart data.
      </div>
    );
  }

  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;

  const width = 600;
  const height = 120;
  const padding = 12;

  const path = closes
    .map((close, index) => {
      const x =
        padding + (index / Math.max(closes.length - 1, 1)) * (width - padding * 2);
      const y =
        height - padding - ((close - min) / range) * (height - padding * 2);

      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <div className="rounded-2xl bg-slate-50 p-3">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-32 w-full">
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          className="text-indigo-500"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>

      <div className="mt-1 flex justify-between text-xs text-slate-400">
        <span>{points[0]?.time ?? "-"}</span>
        <span>{points[points.length - 1]?.time ?? "-"}</span>
      </div>
    </div>
  );
}

export default function StockDetailPanel({ stockId, stockName }: Props) {
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [indicatorData, setIndicatorData] = useState<StockIndicatorPoint[]>([]);
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
          limit: 80,
        }),
        fetchJson<StockIndicatorPoint[]>(
          `/api/market/indicators/${currentStockId}/daily`,
          {
            limit: 80,
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
      setChartData([]);
      setIndicatorData([]);
      setLoadState("idle");
      setErrorMessage(null);
      return;
    }

    void loadStockDetail(stockId);
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
      </div>

      {errorMessage ? (
        <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {errorMessage}
        </div>
      ) : null}

      <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Sparkline points={chartData} />

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
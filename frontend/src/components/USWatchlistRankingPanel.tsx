"use client";

import { fetchJson } from "@/lib/api";
import type {
  USWatchlistRankingItemRead,
  USWatchlistRankingRead,
} from "@/types/market";
import { useCallback, useEffect, useMemo, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type USRankBy = "none" | "change_pct" | "volume" | "close";

type Props = {
  selectedGroupId: number | null;
  selectedGroupName: string | null;
  selectedSymbol: string | null;
  reloadKey: number;
  onSelectSymbol: (symbol: string, securityName: string | null) => void;
};

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

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-slate-500";
  }
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
}

function trendLabel(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (value > 0) return "上漲";
  if (value < 0) return "下跌";
  return "持平";
}

function trendClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "bg-slate-100 text-slate-600";
  }
  if (value > 0) return "bg-red-50 text-red-700";
  if (value < 0) return "bg-emerald-50 text-emerald-700";
  return "bg-slate-100 text-slate-600";
}

function statusLabel(status: string) {
  if (status === "ready") return "Ready";
  if (status === "no_data") return "尚無資料";
  if (status === "error") return "錯誤";
  return status || "-";
}

function rankLabel(rankBy: string) {
  if (rankBy === "none") return "正常排序";
  if (rankBy === "change_pct") return "漲跌幅";
  if (rankBy === "volume") return "成交量";
  if (rankBy === "close") return "收盤價";
  return rankBy;
}

export default function USWatchlistRankingPanel({
  selectedGroupId,
  selectedGroupName,
  selectedSymbol,
  reloadKey,
  onSelectSymbol,
}: Props) {
  const [rankBy, setRankBy] = useState<USRankBy>("none");
  const [ranking, setRanking] = useState<USWatchlistRankingRead | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const sortOrder = rankBy === "none" ? "asc" : "desc";
  const rows = useMemo(() => ranking?.results ?? [], [ranking]);
  const summary = useMemo(() => {
    const upCount = rows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct > 0;
    }).length;
    const downCount = rows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct < 0;
    }).length;

    return {
      stockCount: ranking?.requested_symbol_count ?? rows.length,
      upCount,
      downCount,
      noDataCount: ranking?.no_data_count ?? 0,
    };
  }, [ranking?.no_data_count, ranking?.requested_symbol_count, rows]);

  const loadRanking = useCallback(async () => {
    setLoadState("loading");
    setErrorMessage(null);

    const params: Record<string, string | number | boolean> = {
      include_children: true,
      enabled_only: true,
      rank_by: rankBy,
      sort_order: sortOrder,
    };

    if (selectedGroupId !== null) {
      params.group_id = selectedGroupId;
    }

    try {
      const data = await fetchJson<USWatchlistRankingRead>(
        "/api/us-market/watchlists/ranking",
        params
      );
      setRanking(data);
      setLastUpdatedAt(new Date().toLocaleString("zh-TW", { hour12: false }));
      setLoadState("success");
    } catch (error) {
      setRanking(null);
      setLoadState("error");
      setErrorMessage(error instanceof Error ? error.message : "讀取美股自選排行失敗");
    }
  }, [rankBy, selectedGroupId, sortOrder]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadRanking();
    }, 0);

    return () => window.clearTimeout(timer);
  }, [loadRanking, reloadKey]);

  function renderRow(row: USWatchlistRankingItemRead) {
    const selected = row.symbol === selectedSymbol;

    return (
      <button
        key={`${row.group_id}-${row.symbol}`}
        type="button"
        onClick={() => onSelectSymbol(row.symbol, row.security_name)}
        className={[
          "grid w-full grid-cols-[46px_minmax(160px,1fr)_94px_86px_86px_104px_78px] items-center border-t border-slate-200 px-4 py-2 text-left text-sm",
          selected ? "bg-slate-900 text-white" : "bg-white text-slate-800 hover:bg-slate-50",
        ].join(" ")}
      >
        <span className={selected ? "text-slate-300" : "text-slate-500"}>#{row.rank}</span>
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            {row.symbol} {row.security_name ?? ""}
          </span>
          <span className={selected ? "block truncate text-xs text-slate-300" : "block truncate text-xs text-slate-500"}>
            {[row.exchange, row.asset_type].filter(Boolean).join(" · ") || statusLabel(row.status)}
          </span>
        </span>
        <span className={selected ? "text-slate-300" : "text-slate-500"}>
          {formatDate(row.trade_date)}
        </span>
        <span className="text-right font-semibold">{formatNumber(row.close)}</span>
        <span className={`text-right font-semibold ${selected ? "" : valueTone(row.change_pct)}`}>
          {formatPct(row.change_pct)}
        </span>
        <span className="text-right">{formatVolume(row.volume)}</span>
        <span className="text-right">
          <span
            className={[
              "px-2 py-1 text-xs font-semibold",
              selected ? "bg-white text-slate-900" : trendClass(row.change_pct),
            ].join(" ")}
          >
            {trendLabel(row.change_pct)}
          </span>
        </span>
      </button>
    );
  }

  return (
    <div className="space-y-4">
      <section className="border border-slate-200 bg-white">
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Selected Group
            </div>
            <h2 className="mt-1 text-2xl font-bold text-slate-950">
              {selectedGroupName ?? "美股自選"}
            </h2>
            <div className="mt-1 text-sm text-slate-500">
              {lastUpdatedAt ? `更新時間 ${lastUpdatedAt}` : "尚未更新"}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={rankBy}
              onChange={(event) => setRankBy(event.target.value as USRankBy)}
              className="h-9 border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 outline-none focus:border-red-700"
            >
              <option value="none">正常排序</option>
              <option value="change_pct">漲跌幅</option>
              <option value="volume">成交量</option>
              <option value="close">收盤價</option>
            </select>
            <button
              type="button"
              onClick={() => void loadRanking()}
              className="h-9 bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300"
              disabled={loadState === "loading"}
            >
              Reload
            </button>
          </div>
        </div>

        {errorMessage ? (
          <div className="border-t border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700">
            {errorMessage}
          </div>
        ) : null}

        <div className="grid grid-cols-2 border-t border-slate-200 md:grid-cols-4">
          <div className="px-5 py-3">
            <div className="text-xs text-slate-500">股票數</div>
            <div className="mt-1 text-xl font-bold">{summary.stockCount}</div>
          </div>
          <div className="border-l border-slate-200 px-5 py-3">
            <div className="text-xs text-slate-500">上漲</div>
            <div className="mt-1 text-xl font-bold text-red-600">{summary.upCount}</div>
          </div>
          <div className="border-l border-slate-200 px-5 py-3">
            <div className="text-xs text-slate-500">下跌</div>
            <div className="mt-1 text-xl font-bold text-emerald-600">{summary.downCount}</div>
          </div>
          <div className="border-l border-slate-200 px-5 py-3">
            <div className="text-xs text-slate-500">排序</div>
            <div className="mt-1 text-xl font-bold">{rankLabel(ranking?.rank_by ?? rankBy)}</div>
          </div>
        </div>
      </section>

      <section className="border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <h3 className="text-sm font-bold text-slate-950">自選股列表</h3>
          <span className="text-xs text-slate-500">
            {loadState === "loading"
              ? "Loading"
              : `${rows.length} 檔 · ${summary.noDataCount} 檔尚無資料`}
          </span>
        </div>

        <div className="grid grid-cols-[46px_minmax(160px,1fr)_94px_86px_86px_104px_78px] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
          <span>名次</span>
          <span>股票</span>
          <span>日期</span>
          <span className="text-right">收盤</span>
          <span className="text-right">漲幅</span>
          <span className="text-right">成交量</span>
          <span className="text-right">狀態</span>
        </div>
        {rows.length > 0 ? (
          rows.map(renderRow)
        ) : (
          <div className="border-t border-slate-200 px-5 py-10 text-center text-sm text-slate-500">
            {loadState === "loading" ? "Loading" : "尚無美股自選排行"}
          </div>
        )}
      </section>
    </div>
  );
}

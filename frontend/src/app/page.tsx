"use client";

import SidebarWatchlistExplorer from "@/components/SidebarWatchlistExplorer";
import StockDetailPanel from "@/components/StockDetailPanel";
import { fetchJson } from "@/lib/api";
import type {
  IndicatorsResponse,
  RankingItem,
  RankingResponse,
  SignalsResponse,
  WatchlistGroupNode,
} from "@/types/market";
import { useEffect, useMemo, useState } from "react";

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

function statusClass(status: string) {
  if (status.includes("bullish")) {
    return "bg-emerald-100 text-emerald-700 ring-emerald-200";
  }

  if (status.includes("bearish")) {
    return "bg-rose-100 text-rose-700 ring-rose-200";
  }

  if (status === "no_data" || status === "error") {
    return "bg-slate-100 text-slate-500 ring-slate-200";
  }

  return "bg-indigo-100 text-indigo-700 ring-indigo-200";
}

function changeClass(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-slate-400";
  if (value > 0) return "text-rose-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-600";
}

export default function Home() {
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<WatchlistGroupNode | null>(null);
  const [rankBy, setRankBy] = useState("score");

  const [selectedStockId, setSelectedStockId] = useState<string | null>(null);
  const [selectedStockName, setSelectedStockName] = useState<string | null>(null);

  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [signals, setSignals] = useState<SignalsResponse | null>(null);
  const [indicators, setIndicators] = useState<IndicatorsResponse | null>(null);

  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const indicatorByStockId = useMemo(() => {
    const map = new Map<string, IndicatorsResponse["results"][number]>();

    indicators?.results.forEach((item) => {
      map.set(item.stock_id, item);
    });

    return map;
  }, [indicators]);

  async function loadDashboard(groupId: number, currentRankBy = rankBy) {
    setLoadState("loading");
    setErrorMessage(null);

    try {
      const commonParams = {
        include_children: true,
        enabled_only: true,
        ma_windows: "5,20,60",
        volume_ma_windows: "5,20",
      };

      const [rankingData, signalsData, indicatorsData] = await Promise.all([
        fetchJson<RankingResponse>(`/api/watchlists/groups/${groupId}/rankings/latest`, {
          ...commonParams,
          rank_by: currentRankBy,
          sort_order: "desc",
          limit: 100,
          volume_ratio_threshold: 1.5,
        }),
        fetchJson<SignalsResponse>(`/api/watchlists/groups/${groupId}/signals/latest`, {
          ...commonParams,
          limit: 100,
          volume_ratio_threshold: 1.5,
        }),
        fetchJson<IndicatorsResponse>(`/api/watchlists/groups/${groupId}/indicators/latest`, {
          ...commonParams,
        }),
      ]);

      setRanking(rankingData);
      setSignals(signalsData);
      setIndicators(indicatorsData);
      setLastUpdatedAt(
        new Date().toLocaleString("zh-TW", {
          hour12: false,
        })
      );
      setLoadState("success");
    } catch (error) {
      setLoadState("error");
      setErrorMessage(error instanceof Error ? error.message : "Unknown error");
    }
  }

  useEffect(() => {
    if (selectedGroupId !== null) {
      void loadDashboard(selectedGroupId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGroupId]);

  function handleSelectGroup(group: WatchlistGroupNode | null) {
    setSelectedGroup(group);
    setSelectedGroupId(group?.id ?? null);

    if (group === null) {
      setRanking(null);
      setSignals(null);
      setIndicators(null);
    }
  }

  function handleSelectStock(stockId: string, stockName: string | null) {
    setSelectedStockId(stockId);
    setSelectedStockName(stockName);
  }

  function handleRankByChange(value: string) {
    setRankBy(value);

    if (selectedGroupId !== null) {
      void loadDashboard(selectedGroupId, value);
    }
  }

  const rows: RankingItem[] = ranking?.results ?? [];

  return (
    <main className="h-screen overflow-hidden bg-slate-100 text-slate-950">
      <div className="flex h-full w-full min-w-[1280px] gap-5 px-5 py-5">
        <SidebarWatchlistExplorer
          selectedGroupId={selectedGroupId}
          onSelectGroup={handleSelectGroup}
          onSelectStock={handleSelectStock}
          onChanged={async (nextGroupId) => {
            const groupId = nextGroupId === undefined ? selectedGroupId : nextGroupId;

            if (groupId !== null) {
              await loadDashboard(groupId);
            } else {
              setRanking(null);
              setSignals(null);
              setIndicators(null);
            }
          }}
        />

        <section className="h-full flex-1 space-y-5 overflow-y-auto pr-1">
          <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-slate-500">Selected Group</p>
                <h2 className="mt-1 text-3xl font-bold tracking-tight">
                  {selectedGroup?.group_name ?? "No group selected"}
                </h2>
                <p className="mt-2 text-sm text-slate-500">
                  {selectedGroup?.description ?? "選擇左側分類後會載入資料。"}
                </p>
                {lastUpdatedAt ? (
                  <p className="mt-2 text-xs text-slate-400">
                    Last refresh: {lastUpdatedAt}
                  </p>
                ) : null}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <select
                  value={rankBy}
                  onChange={(event) => handleRankByChange(event.target.value)}
                  className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm outline-none focus:border-indigo-400"
                >
                  <option value="score">Score</option>
                  <option value="change_pct">Change %</option>
                  <option value="volume">Volume</option>
                  <option value="close">Close</option>
                </select>

                <button
                  type="button"
                  onClick={() => {
                    if (selectedGroupId !== null) {
                      void loadDashboard(selectedGroupId);
                    }
                  }}
                  className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700"
                >
                  Reload
                </button>
              </div>
            </div>

            {errorMessage ? (
              <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
                {errorMessage}
              </div>
            ) : null}

            <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-4">
              <div className="rounded-2xl bg-slate-50 p-4">
                <p className="text-xs font-medium text-slate-500">Stocks</p>
                <p className="mt-2 text-2xl font-bold">
                  {ranking?.requested_stock_count ?? "-"}
                </p>
              </div>

              <div className="rounded-2xl bg-emerald-50 p-4">
                <p className="text-xs font-medium text-emerald-600">Bullish</p>
                <p className="mt-2 text-2xl font-bold text-emerald-700">
                  {signals?.bullish_count ?? "-"}
                </p>
              </div>

              <div className="rounded-2xl bg-rose-50 p-4">
                <p className="text-xs font-medium text-rose-600">Bearish</p>
                <p className="mt-2 text-2xl font-bold text-rose-700">
                  {signals?.bearish_count ?? "-"}
                </p>
              </div>

              <div className="rounded-2xl bg-indigo-50 p-4">
                <p className="text-xs font-medium text-indigo-600">Rank By</p>
                <p className="mt-2 text-2xl font-bold text-indigo-700">
                  {ranking?.rank_by ?? rankBy}
                </p>
              </div>
            </div>
          </div>
          <StockDetailPanel stockId={selectedStockId} stockName={selectedStockName} />
          
          <div className="overflow-hidden rounded-3xl border border-white/70 bg-white/80 shadow-sm backdrop-blur">
            <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
              <div>
                <h2 className="text-lg font-bold">Ranking</h2>
                <p className="text-sm text-slate-500">
                  依 {ranking?.rank_by ?? rankBy} 排序，自選股最新狀態。
                </p>
              </div>

              <div className="text-sm text-slate-500">
                {loadState === "loading" ? "Loading..." : `${rows.length} rows`}
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[960px] text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-6 py-3">Rank</th>
                    <th className="px-6 py-3">Stock</th>
                    <th className="px-6 py-3">Date</th>
                    <th className="px-6 py-3 text-right">Close</th>
                    <th className="px-6 py-3 text-right">Change</th>
                    <th className="px-6 py-3 text-right">Volume</th>
                    <th className="px-6 py-3 text-right">Score</th>
                    <th className="px-6 py-3">Status</th>
                    <th className="px-6 py-3">Primary Signal</th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-slate-100">
                  {rows.map((row) => {
                    const indicator = indicatorByStockId.get(row.stock_id);

                    return (
                      <tr
                          key={row.stock_id}
                          onClick={() => handleSelectStock(row.stock_id, row.stock_name)}
                          className="cursor-pointer hover:bg-slate-50/80"
                        >
                        <td className="px-6 py-4 font-semibold text-slate-500">
                          #{row.rank}
                        </td>

                        <td className="px-6 py-4">
                          <div className="font-semibold">{row.stock_id}</div>
                          <div className="text-xs text-slate-500">
                            {row.stock_name ?? "-"}
                          </div>
                        </td>

                        <td className="px-6 py-4 text-slate-500">{row.time ?? "-"}</td>

                        <td className="px-6 py-4 text-right font-medium">
                          {formatPrice(row.close)}
                        </td>

                        <td
                          className={[
                            "px-6 py-4 text-right font-semibold",
                            changeClass(row.change_pct),
                          ].join(" ")}
                        >
                          {formatPct(row.change_pct)}
                        </td>

                        <td className="px-6 py-4 text-right text-slate-600">
                          {formatNumber(row.volume)}
                        </td>

                        <td className="px-6 py-4 text-right font-semibold">{row.score}</td>

                        <td className="px-6 py-4">
                          <span
                            className={[
                              "inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1",
                              statusClass(row.status),
                            ].join(" ")}
                          >
                            {row.status}
                          </span>
                        </td>

                        <td className="px-6 py-4">
                          <div className="font-medium">
                            {row.primary_signal_label ?? "-"}
                          </div>
                          <div className="mt-1 text-xs text-slate-400">
                            MA20: {formatPrice(indicator?.ma?.["ma20"])}
                          </div>
                        </td>
                      </tr>
                    );
                  })}

                  {rows.length === 0 ? (
                    <tr>
                      <td className="px-6 py-10 text-center text-slate-400" colSpan={9}>
                        No ranking data.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
              <h2 className="text-lg font-bold">Signals</h2>
              <p className="mt-1 text-sm text-slate-500">
                顯示每檔股票目前觸發的可讀訊號。
              </p>

              <div className="mt-4 space-y-3">
                {signals?.results.map((item) => (
                  <div key={item.stock_id} className="rounded-2xl bg-slate-50 p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-semibold">
                          {item.stock_id} {item.stock_name}
                        </div>
                        <div className="text-xs text-slate-500">
                          score {item.score} · {item.status}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2">
                      {item.signals.map((signal) => (
                        <span
                          key={signal.key}
                          className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-slate-200"
                          title={signal.message}
                        >
                          {signal.label}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}

                {!signals || signals.results.length === 0 ? (
                  <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-400">
                    No signal data.
                  </div>
                ) : null}
              </div>
            </div>

            <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
              <h2 className="text-lg font-bold">Indicators</h2>
              <p className="mt-1 text-sm text-slate-500">最新均線與量均線摘要。</p>

              <div className="mt-4 space-y-3">
                {indicators?.results.map((item) => (
                  <div key={item.stock_id} className="rounded-2xl bg-slate-50 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-semibold">
                          {item.stock_id} {item.stock_name}
                        </div>
                        <div className="text-xs text-slate-500">
                          {item.time} · {item.status}
                        </div>
                      </div>

                      <div className="text-right">
                        <div className="font-semibold">{formatPrice(item.close)}</div>
                        <div
                          className={[
                            "text-xs font-medium",
                            changeClass(item.change_pct),
                          ].join(" ")}
                        >
                          {formatPct(item.change_pct)}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
                      <div className="rounded-xl bg-white px-3 py-2">
                        MA5: {formatPrice(item.ma["ma5"])}
                      </div>
                      <div className="rounded-xl bg-white px-3 py-2">
                        MA20: {formatPrice(item.ma["ma20"])}
                      </div>
                      <div className="rounded-xl bg-white px-3 py-2">
                        VMA5: {formatNumber(item.volume_ma["volume_ma5"])}
                      </div>
                      <div className="rounded-xl bg-white px-3 py-2">
                        VMA20: {formatNumber(item.volume_ma["volume_ma20"])}
                      </div>
                    </div>
                  </div>
                ))}

                {!indicators || indicators.results.length === 0 ? (
                  <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-400">
                    No indicator data.
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
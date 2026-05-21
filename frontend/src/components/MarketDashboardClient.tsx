"use client";

import SidebarWatchlistExplorer from "@/components/SidebarWatchlistExplorer";
import StockDetailPanel from "@/components/StockDetailPanel";
import { fetchJson } from "@/lib/api";
import type {
  ChartPoint,
  IndicatorsResponse,
  RankingItem,
  RankingResponse,
  SignalsResponse,
  StockIndicatorPoint,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";
import { useEffect, useMemo, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type Props = {
  initialTree: WatchlistGroupNode[];
  initialItems: WatchlistItemRead[];
  initialSelectedGroupId: number | null;
  initialChartData: ChartPoint[];
  initialIndicatorData: StockIndicatorPoint[];
};

const navItems = ["首頁", "自選股", "大盤指數", "ETF", "應用市集", "新聞話題", "名師專欄", "影音專區", "熱力圖", "更多"];

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(value);
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
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

function statusLabel(status: string) {
  if (status.includes("bullish")) return "偏多";
  if (status.includes("bearish")) return "偏空";
  if (status === "no_data") return "無資料";
  if (status === "error") return "錯誤";
  return "中性";
}

function statusClass(status: string) {
  if (status.includes("bullish")) return "bg-red-50 text-red-700";
  if (status.includes("bearish")) return "bg-emerald-50 text-emerald-700";
  if (status === "error") return "bg-amber-50 text-amber-700";
  return "bg-slate-100 text-slate-600";
}

function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
}

export default function MarketDashboardClient({
  initialTree,
  initialItems,
  initialSelectedGroupId,
  initialChartData,
  initialIndicatorData,
}: Props) {
  const initialSelectedGroup = useMemo(() => {
    return flattenGroups(initialTree).find((group) => group.id === initialSelectedGroupId) ?? null;
  }, [initialTree, initialSelectedGroupId]);
  const initialSelectedItem = useMemo(() => {
    return (
      initialItems.find((item) => {
        return initialSelectedGroupId === null || item.group_id === initialSelectedGroupId;
      }) ??
      initialItems[0] ??
      null
    );
  }, [initialItems, initialSelectedGroupId]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(
    initialSelectedGroup?.id ?? null
  );
  const [selectedGroup, setSelectedGroup] = useState<WatchlistGroupNode | null>(
    initialSelectedGroup
  );
  const [selectedStockId, setSelectedStockId] = useState<string | null>(
    initialSelectedItem?.stock_id ?? null
  );
  const [selectedStockName, setSelectedStockName] = useState<string | null>(
    initialSelectedItem?.stock_name ?? null
  );
  const [rankBy, setRankBy] = useState("score");
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [signals, setSignals] = useState<SignalsResponse | null>(null);
  const [indicators, setIndicators] = useState<IndicatorsResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const rows = useMemo(() => ranking?.results ?? [], [ranking]);

  const indicatorByStockId = useMemo(() => {
    const map = new Map<string, IndicatorsResponse["results"][number]>();
    indicators?.results.forEach((item) => map.set(item.stock_id, item));
    return map;
  }, [indicators]);

  const topSignals = useMemo(() => {
    return signals?.results.filter((item) => item.signals.length > 0).slice(0, 4) ?? [];
  }, [signals]);

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
      if (!selectedStockId && rankingData.results.length > 0) {
        setSelectedStockId(rankingData.results[0].stock_id);
        setSelectedStockName(rankingData.results[0].stock_name);
      }
      setLastUpdatedAt(new Date().toLocaleString("zh-TW", { hour12: false }));
      setLoadState("success");
    } catch (error) {
      setLoadState("error");
      setErrorMessage(error instanceof Error ? error.message : "資料讀取失敗");
    }
  }

  useEffect(() => {
    if (selectedGroupId === null) return;

    const timer = window.setTimeout(() => {
      void loadDashboard(selectedGroupId);
    }, 0);

    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGroupId]);

  function handleSelectGroup(group: WatchlistGroupNode | null) {
    setSelectedGroup(group);
    setSelectedGroupId(group?.id ?? null);

    if (group !== null) {
      setSelectedStockId(null);
      setSelectedStockName(null);
    } else {
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

  function renderRankingRow(row: RankingItem) {
    const selected = row.stock_id === selectedStockId;
    const indicator = indicatorByStockId.get(row.stock_id);

    return (
      <button
        key={row.stock_id}
        type="button"
        onClick={() => handleSelectStock(row.stock_id, row.stock_name)}
        className={[
          "grid w-full grid-cols-[52px_minmax(120px,1fr)_88px_88px_88px_90px] items-center border-t border-slate-200 px-4 py-2 text-left text-sm",
          selected ? "bg-slate-900 text-white" : "bg-white text-slate-800 hover:bg-slate-50",
        ].join(" ")}
      >
        <span className={selected ? "text-slate-300" : "text-slate-500"}>#{row.rank}</span>
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            {row.stock_id} {row.stock_name ?? ""}
          </span>
          <span className={selected ? "block truncate text-xs text-slate-300" : "block truncate text-xs text-slate-500"}>
            {row.primary_signal_label ?? statusLabel(row.status)}
          </span>
        </span>
        <span className="text-right font-semibold">{formatPrice(row.close)}</span>
        <span className={`text-right font-semibold ${selected ? "" : valueTone(row.change_pct)}`}>
          {formatPct(row.change_pct)}
        </span>
        <span className="text-right">{formatNumber(row.volume)}</span>
        <span className="text-right">
          <span
            className={[
              "px-2 py-1 text-xs font-semibold",
              selected ? "bg-white text-slate-900" : statusClass(row.status),
            ].join(" ")}
          >
            {indicator?.status ? statusLabel(indicator.status) : statusLabel(row.status)}
          </span>
        </span>
      </button>
    );
  }

  return (
    <main className="h-screen overflow-hidden bg-slate-100 text-slate-950">
      <div className="flex h-full min-w-[1180px] flex-col">
        <nav className="flex h-12 shrink-0 items-center bg-red-700 px-8 text-white">
          <div className="mr-8 text-sm font-bold tracking-[0.18em]">OMI</div>
          <div className="flex h-full items-center">
            {navItems.map((item) => (
              <button
                key={item}
                type="button"
                className={[
                  "h-full px-5 text-base font-bold transition",
                  item === "自選股" ? "bg-red-900" : "hover:bg-red-800",
                ].join(" ")}
              >
                {item}
              </button>
            ))}
          </div>
        </nav>

        <div className="flex min-h-0 flex-1">
          <SidebarWatchlistExplorer
            initialTree={initialTree}
            initialItems={initialItems}
            selectedGroupId={selectedGroupId}
            selectedStockId={selectedStockId}
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

          <section className="min-w-0 flex-1 overflow-y-auto p-4">
            <div className="mb-4 border border-slate-200 bg-white">
              <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Selected Group
                  </div>
                  <h2 className="mt-1 text-2xl font-bold text-slate-950">
                    {selectedGroup?.group_name ?? "尚未選擇分組"}
                  </h2>
                  <div className="mt-1 text-sm text-slate-500">
                    {lastUpdatedAt ? `更新時間 ${lastUpdatedAt}` : "選擇左側分組後載入資料"}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <select
                    value={rankBy}
                    onChange={(event) => handleRankByChange(event.target.value)}
                    className="h-9 border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 outline-none focus:border-red-700"
                  >
                    <option value="score">Score</option>
                    <option value="change_pct">Change %</option>
                    <option value="volume">Volume</option>
                    <option value="close">Close</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => {
                      if (selectedGroupId !== null) void loadDashboard(selectedGroupId);
                    }}
                    className="h-9 bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300"
                    disabled={selectedGroupId === null || loadState === "loading"}
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
                  <div className="mt-1 text-xl font-bold">{ranking?.requested_stock_count ?? "-"}</div>
                </div>
                <div className="border-l border-slate-200 px-5 py-3">
                  <div className="text-xs text-slate-500">偏多</div>
                  <div className="mt-1 text-xl font-bold text-red-600">{signals?.bullish_count ?? "-"}</div>
                </div>
                <div className="border-l border-slate-200 px-5 py-3">
                  <div className="text-xs text-slate-500">偏空</div>
                  <div className="mt-1 text-xl font-bold text-emerald-600">{signals?.bearish_count ?? "-"}</div>
                </div>
                <div className="border-l border-slate-200 px-5 py-3">
                  <div className="text-xs text-slate-500">排序</div>
                  <div className="mt-1 text-xl font-bold">{ranking?.rank_by ?? rankBy}</div>
                </div>
              </div>
            </div>

            <StockDetailPanel
              stockId={selectedStockId}
              stockName={selectedStockName}
              initialChartData={initialChartData}
              initialIndicatorData={initialIndicatorData}
            />

            <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
              <section className="border border-slate-200 bg-white">
                <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
                  <h3 className="text-sm font-bold text-slate-950">自選股排行</h3>
                  <span className="text-xs text-slate-500">
                    {loadState === "loading" ? "載入中" : `${rows.length} 檔`}
                  </span>
                </div>
                <div className="grid grid-cols-[52px_minmax(120px,1fr)_88px_88px_88px_90px] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
                  <span>Rank</span>
                  <span>Stock</span>
                  <span className="text-right">Close</span>
                  <span className="text-right">Change</span>
                  <span className="text-right">Volume</span>
                  <span className="text-right">Status</span>
                </div>
                {rows.length > 0 ? (
                  rows.map(renderRankingRow)
                ) : (
                  <div className="border-t border-slate-200 px-5 py-10 text-center text-sm text-slate-500">
                    尚無排行資料
                  </div>
                )}
              </section>

              <section className="border border-slate-200 bg-white">
                <div className="border-b border-slate-200 px-5 py-3">
                  <h3 className="text-sm font-bold text-slate-950">即時訊號摘要</h3>
                </div>
                <div className="divide-y divide-slate-200">
                  {topSignals.length > 0 ? (
                    topSignals.map((item) => (
                      <button
                        key={item.stock_id}
                        type="button"
                        onClick={() => handleSelectStock(item.stock_id, item.stock_name)}
                        className="block w-full px-5 py-3 text-left hover:bg-slate-50"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-bold text-slate-950">
                              {item.stock_id} {item.stock_name ?? ""}
                            </div>
                            <div className="mt-1 truncate text-xs text-slate-500">
                              {item.signals[0]?.label ?? statusLabel(item.status)}
                            </div>
                          </div>
                          <div className={`text-sm font-bold ${valueTone(item.change_pct)}`}>
                            {formatPct(item.change_pct)}
                          </div>
                        </div>
                      </button>
                    ))
                  ) : (
                    <div className="px-5 py-10 text-center text-sm text-slate-500">
                      尚無訊號
                    </div>
                  )}
                </div>
              </section>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

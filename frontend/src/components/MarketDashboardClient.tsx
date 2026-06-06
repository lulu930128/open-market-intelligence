"use client";

import SidebarWatchlistExplorer from "@/components/SidebarWatchlistExplorer";
import type { MarketRegion } from "@/components/SidebarWatchlistExplorer";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import StockDetailPanel from "@/components/StockDetailPanel";
import USStockDetailPanel from "@/components/USStockDetailPanel";
import USWatchlistSidebar from "@/components/USWatchlistSidebar";
import { fetchJson } from "@/lib/api";
import { formatJobStatus, requestBackfillJob } from "@/lib/jobs";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  getTaiwanIntradayXRatio,
  getTaiwanMarketRefreshState,
  isTaiwanRegularSessionPoint,
} from "@/lib/taiwanMarketTime";
import {
  US_INTRADAY_REFRESH_MS,
  getUsIntradayXRatio,
  getUsMarketRefreshState,
  isUsRegularSessionPoint,
} from "@/lib/usMarketTime";
import type {
  ChartPoint,
  MarketIndexSnapshot,
  MarketIndexSummary,
  RankingItem,
  RankingResponse,
  StockIndicatorPoint,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  USWatchlistRankingItemRead,
  USWatchlistRankingRead,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type RankBy = "none" | "change_pct" | "score" | "volume";
type USRankBy = "none" | "change_pct" | "volume" | "close";
const WATCHLIST_INTRADAY_LIMIT = 30;
type RankingDisplayRow = {
  key: string;
  rank: number;
  symbol: string;
  name: string | null;
  meta: string | null;
  visual: ReactNode;
  close: string;
  closeValue: number | null | undefined;
  change: string;
  changePct: number | null | undefined;
  trend: string;
  volume: string;
  volumeValue: number | null | undefined;
  selected: boolean;
  onSelect: () => void;
};
type RankingPanelOption = {
  value: string;
  label: string;
};
type Props = {
  initialTree: WatchlistGroupNode[];
  initialItems: WatchlistItemRead[];
  initialSelectedGroupId: number | null;
  initialChartData: ChartPoint[];
  initialIndicatorData: StockIndicatorPoint[];
  initialRankingData: RankingResponse | null;
  initialMarketIndexSummary: MarketIndexSummary | null;
  initialUsWatchlistTree: USWatchlistGroupNode[];
  initialUsWatchlistItems: USWatchlistItemRead[];
};

function formatLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value / 1000));
}

function formatWholeNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatSignedNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";

  return `${sign}${value.toLocaleString("zh-TW", {
    maximumFractionDigits: 2,
  })}`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatTradeValueYi(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return (value / 100_000_000).toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-slate-500";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
}

function statusLabel(status: string) {
  if (status === "pending") return "-";
  if (status === "intraday") return "盤中";
  if (status.includes("bullish")) return "偏多";
  if (status.includes("bearish")) return "偏空";
  if (status === "no_data") return "無資料";
  if (status === "error") return "錯誤";
  return "中性";
}

function rankLabel(rankBy: string) {
  if (rankBy === "none" || rankBy === "watchlist") return "正常排序";
  if (rankBy === "change_pct") return "漲幅";
  if (rankBy === "volume") return "成交量";
  if (rankBy === "close") return "收盤價";
  return "Score";
}

function trendLabel(
  value: number | null | undefined,
  limitStatus?: RankingItem["limit_status"]
) {
  if (limitStatus === "limit_up") return "漲停";
  if (limitStatus === "limit_down") return "跌停";
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (value > 0) return "上漲";
  if (value < 0) return "下跌";
  return "持平";
}

function trendClass(
  value: number | null | undefined,
  limitStatus?: RankingItem["limit_status"]
) {
  if (limitStatus === "limit_up") return "bg-red-600 text-white shadow-sm";
  if (limitStatus === "limit_down") return "bg-emerald-600 text-white shadow-sm";
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "bg-slate-100 text-slate-600";
  }
  if (value > 0) return "bg-red-50 text-red-700";
  if (value < 0) return "bg-emerald-50 text-emerald-700";
  return "bg-slate-100 text-slate-600";
}

function selectedTrendClass(limitStatus?: RankingItem["limit_status"]) {
  if (limitStatus === "limit_up") return "bg-red-500 text-white";
  if (limitStatus === "limit_down") return "bg-emerald-500 text-white";
  return "bg-white text-slate-900";
}

function sparklineTone(
  latestPrice: number | null,
  previousClose: number | null,
  selected: boolean
) {
  if (latestPrice === null || previousClose === null || previousClose === 0) {
    return selected ? "stroke-slate-300" : "stroke-slate-400";
  }

  if (latestPrice > previousClose) return "stroke-red-500";
  if (latestPrice < previousClose) return "stroke-emerald-500";
  return selected ? "stroke-slate-300" : "stroke-slate-400";
}

function formatRowTime(value: string | null | undefined) {
  if (!value) return null;

  const date = new Date(value);

  if (Number.isNaN(date.getTime()) || !value.includes("T")) return value;

  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Taipei",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value])
  );

  return `${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`;
}

function formatDashboardTime(value: Date) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })
      .formatToParts(value)
      .map((part) => [part.type, part.value])
  );

  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function buildSparklinePath(
  points: Array<{ time: string; price: number }>,
  previousClose: number | null,
  getXRatio: (value: string | Date) => number = getTaiwanIntradayXRatio
) {
  const width = 92;
  const height = 28;
  const paddingX = 2;
  const paddingY = 4;
  const usableWidth = width - paddingX * 2;
  const usableHeight = height - paddingY * 2;
  const prices = [
    ...points.map((point) => point.price),
    ...(previousClose !== null ? [previousClose] : []),
  ];
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const range = maxPrice - minPrice || Math.max(maxPrice * 0.01, 1);
  const yMin = minPrice - range * 0.08;
  const yMax = maxPrice + range * 0.08;
  const yRange = yMax - yMin || 1;
  const path = points
    .map((point, index) => {
      const x = paddingX + getXRatio(point.time) * usableWidth;
      const y = paddingY + ((yMax - point.price) / yRange) * usableHeight;

      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const previousCloseY =
    previousClose === null
      ? null
      : paddingY + ((yMax - previousClose) / yRange) * usableHeight;
  const latestPoint = points[points.length - 1];
  const latestPointX = paddingX + getXRatio(latestPoint.time) * usableWidth;
  const latestPointY = paddingY + ((yMax - latestPoint.price) / yRange) * usableHeight;

  return { path, previousCloseY, latestPointX, latestPointY, width, height };
}

function sparklinePointTone(
  latestPrice: number | null,
  previousClose: number | null,
  selected: boolean
) {
  if (latestPrice !== null && previousClose !== null && previousClose !== 0) {
    if (latestPrice > previousClose) {
      return {
        core: selected ? "fill-red-300" : "fill-red-500",
        ring: selected ? "stroke-red-200" : "stroke-red-400",
      };
    }

    if (latestPrice < previousClose) {
      return {
        core: selected ? "fill-emerald-300" : "fill-emerald-500",
        ring: selected ? "stroke-emerald-200" : "stroke-emerald-400",
      };
    }
  }

  return {
    core: selected ? "fill-slate-200" : "fill-slate-400",
    ring: selected ? "stroke-slate-300" : "stroke-slate-300",
  };
}

function RankingSparkline({
  row,
  selected,
}: {
  row: RankingItem;
  selected: boolean;
}) {
  const points = (row.intraday_points ?? []).filter((point) => {
    return (
      point.time &&
      point.price !== null &&
      point.price !== undefined &&
      !Number.isNaN(point.price) &&
      isTaiwanRegularSessionPoint(point.time)
    );
  });

  if (points.length < 2) {
    return (
      <span className={selected ? "text-center text-xs text-slate-400" : "text-center text-xs text-slate-400"}>
        -
      </span>
    );
  }

  const previousClose = row.intraday_previous_close ?? null;
  const latestPrice = points[points.length - 1]?.price ?? null;
  const chart = buildSparklinePath(points, previousClose);
  const latestPoint = points[points.length - 1];
  const pointTone = sparklinePointTone(latestPrice, previousClose, selected);

  return (
    <svg
      viewBox={`0 0 ${chart.width} ${chart.height}`}
      className="h-8 w-[92px]"
      aria-label="當日走勢"
    >
      <rect width={chart.width} height={chart.height} fill="transparent" />
      {chart.previousCloseY !== null ? (
        <line
          x1="2"
          x2={chart.width - 2}
          y1={chart.previousCloseY}
          y2={chart.previousCloseY}
          className={selected ? "stroke-slate-600" : "stroke-slate-200"}
          strokeDasharray="3 3"
        />
      ) : null}
      <path
        d={chart.path}
        fill="none"
        strokeWidth="1.8"
        className={sparklineTone(latestPrice, previousClose, selected)}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g
        key={`${latestPoint.time}-${latestPoint.price}`}
        className="omi-live-sparkline-point"
        pointerEvents="none"
      >
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="5.5"
          className={`omi-live-point-ring ${pointTone.ring}`}
        />
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="2.2"
          className={`omi-live-point-core ${pointTone.core}`}
        />
      </g>
    </svg>
  );
}

function USRankingSparkline({
  row,
  selected,
}: {
  row: USWatchlistRankingItemRead;
  selected: boolean;
}) {
  const points = (row.intraday_points ?? []).filter((point) => {
    return (
      point.time &&
      point.price !== null &&
      point.price !== undefined &&
      !Number.isNaN(point.price) &&
      isUsRegularSessionPoint(point.time)
    );
  });

  if (points.length < 2) {
    return (
      <span className={selected ? "text-center text-xs text-slate-400" : "text-center text-xs text-slate-400"}>
        {row.time ? "盤中" : "-"}
      </span>
    );
  }

  const previousClose = row.intraday_previous_close ?? null;
  const latestPrice = points[points.length - 1]?.price ?? null;
  const chart = buildSparklinePath(points, previousClose, getUsIntradayXRatio);
  const latestPoint = points[points.length - 1];
  const pointTone = sparklinePointTone(latestPrice, previousClose, selected);

  return (
    <svg
      viewBox={`0 0 ${chart.width} ${chart.height}`}
      className="h-8 w-[92px]"
      aria-label="US intraday trend"
    >
      <rect width={chart.width} height={chart.height} fill="transparent" />
      {chart.previousCloseY !== null ? (
        <line
          x1="2"
          x2={chart.width - 2}
          y1={chart.previousCloseY}
          y2={chart.previousCloseY}
          className={selected ? "stroke-slate-600" : "stroke-slate-200"}
          strokeDasharray="3 3"
        />
      ) : null}
      <path
        d={chart.path}
        fill="none"
        strokeWidth="1.8"
        className={sparklineTone(latestPrice, previousClose, selected)}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g
        key={`${latestPoint.time}-${latestPoint.price}`}
        className="omi-live-sparkline-point"
        pointerEvents="none"
      >
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="5.5"
          className={`omi-live-point-ring ${pointTone.ring}`}
        />
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="2.2"
          className={`omi-live-point-core ${pointTone.core}`}
        />
      </g>
    </svg>
  );
}

function marketRegimeLabel(index: MarketIndexSnapshot) {
  if (index.close === null || index.close === undefined) return "資料不足";
  if (index.price_vs_ma20 !== null && index.price_vs_ma20 !== undefined) {
    if (index.price_vs_ma20 > 1) return "站上 MA20";
    if (index.price_vs_ma20 < -1) return "跌破 MA20";
  }

  if (index.change_pct !== null && index.change_pct !== undefined) {
    if (index.change_pct > 0) return "短線偏多";
    if (index.change_pct < 0) return "短線偏弱";
  }

  return "中性震盪";
}

function MarketTape({
  summary,
  loadState,
}: {
  summary: MarketIndexSummary | null;
  loadState: LoadState;
}) {
  const indices = summary?.indices ?? [];
  const asOf = summary?.as_of ? formatDashboardTime(new Date(summary.as_of)) : null;

  return (
    <section className="mb-3 border border-slate-200 bg-white">
      <div className="grid gap-px bg-slate-200 lg:grid-cols-2">
        {indices.length > 0 ? (
          indices.map((index) => {
            const breadth = index.breadth;
            const advanceRatio =
              breadth && breadth.total_count > 0
                ? (breadth.advance_count / breadth.total_count) * 100
                : null;

            return (
              <div key={index.index_id} className="bg-white px-4 py-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                      Market
                    </div>
                    <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="text-lg font-bold text-slate-950">{index.label}</span>
                      <span className="text-2xl font-black text-slate-950">
                        {formatPrice(index.close)}
                      </span>
                      <span className={`text-sm font-bold ${valueTone(index.change_pct)}`}>
                        {formatSignedNumber(index.change)} / {formatPct(index.change_pct)}
                      </span>
                    </div>
                  </div>
                  <div className="text-right text-xs">
                    <div className="font-semibold text-slate-900">{marketRegimeLabel(index)}</div>
                    <div className={valueTone(index.price_vs_ma20)}>
                      {formatPct(index.price_vs_ma20)} vs MA20
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div className="border border-slate-100 bg-slate-50 px-2 py-2">
                    <div className="text-slate-500">成交金額(億)</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {formatTradeValueYi(index.trade_value)}
                    </div>
                  </div>
                  <div className="border border-slate-100 bg-slate-50 px-2 py-2">
                    <div className="text-slate-500">上漲 / 下跌</div>
                    <div className="mt-1 font-semibold">
                      <span className="text-red-600">{breadth?.advance_count ?? "-"}</span>
                      <span className="px-1 text-slate-400">/</span>
                      <span className="text-emerald-600">{breadth?.decline_count ?? "-"}</span>
                    </div>
                  </div>
                  <div className="border border-slate-100 bg-slate-50 px-2 py-2">
                    <div className="text-slate-500">廣度</div>
                    <div className={`mt-1 font-semibold ${valueTone((advanceRatio ?? 50) - 50)}`}>
                      {advanceRatio === null ? "-" : `${advanceRatio.toFixed(0)}% 上漲`}
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        ) : (
          <div className="bg-white px-4 py-3 text-sm text-slate-500">
            {loadState === "loading" ? "市場指數載入中..." : "市場指數暫無資料"}
          </div>
        )}
      </div>
      <div className="border-t border-slate-200 px-4 py-2 text-xs text-slate-500">
        {asOf ? `市場環境更新 ${asOf}` : "市場環境等待更新"}
      </div>
    </section>
  );
}

function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
}

function flattenUsGroups(nodes: USWatchlistGroupNode[]): USWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenUsGroups(node.children)]);
}

function buildWatchlistRows(
  group: WatchlistGroupNode | null,
  items: WatchlistItemRead[]
): RankingItem[] {
  if (!group) return [];

  const itemsByGroupId = new Map<number, WatchlistItemRead[]>();
  const seenStockIds = new Set<string>();
  const rows: RankingItem[] = [];

  items.forEach((item) => {
    if (!item.enabled) return;

    const groupItems = itemsByGroupId.get(item.group_id) ?? [];
    groupItems.push(item);
    itemsByGroupId.set(item.group_id, groupItems);
  });

  function appendGroupRows(currentGroup: WatchlistGroupNode) {
    (itemsByGroupId.get(currentGroup.id) ?? []).forEach((item) => {
      if (seenStockIds.has(item.stock_id)) return;

      seenStockIds.add(item.stock_id);
      rows.push({
        rank: rows.length + 1,
        stock_id: item.stock_id,
        stock_name: item.stock_name,
        time: null,
        close: null,
        volume: null,
        change: null,
        previous_close: null,
        change_pct: null,
        limit_status: null,
        score: null,
        status: "pending",
        signal_count: 0,
        signal_keys: [],
        primary_signal_key: null,
        primary_signal_label: null,
        intraday_previous_close: null,
        intraday_points: [],
        error_message: null,
      });
    });

    currentGroup.children.forEach(appendGroupRows);
  }

  appendGroupRows(group);
  return rows;
}

function mergeWatchlistRows(
  baseRows: RankingItem[],
  ranking: RankingResponse | null
) {
  if (!ranking) return baseRows;

  const rankingByStockId = new Map(
    ranking.results.map((row) => [row.stock_id, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingByStockId.get(row.stock_id) ?? {}),
    rank: index + 1,
  }));
}

function buildUsWatchlistRows(
  group: USWatchlistGroupNode | null,
  items: USWatchlistItemRead[]
): USWatchlistRankingItemRead[] {
  if (!group) return [];

  const itemsByGroupId = new Map<number, USWatchlistItemRead[]>();
  const seenSymbols = new Set<string>();
  const rows: USWatchlistRankingItemRead[] = [];

  items.forEach((item) => {
    if (!item.enabled) return;

    const groupItems = itemsByGroupId.get(item.group_id) ?? [];
    groupItems.push(item);
    itemsByGroupId.set(item.group_id, groupItems);
  });

  function appendGroupRows(currentGroup: USWatchlistGroupNode) {
    (itemsByGroupId.get(currentGroup.id) ?? []).forEach((item) => {
      const symbol = item.symbol.toUpperCase();
      if (seenSymbols.has(symbol)) return;

      seenSymbols.add(symbol);
      rows.push({
        rank: rows.length + 1,
        symbol,
        security_name: item.security_name,
        exchange: item.exchange,
        asset_type: item.asset_type,
        group_id: item.group_id,
        trade_date: null,
        time: null,
        close: null,
        previous_close: null,
        change: null,
        change_pct: null,
        volume: null,
        status: "pending",
        source: null,
        intraday_previous_close: null,
        intraday_points: [],
        error_message: null,
      });
    });

    currentGroup.children.forEach(appendGroupRows);
  }

  appendGroupRows(group);
  return rows;
}

function firstUsWatchlistRow(
  group: USWatchlistGroupNode | null,
  items: USWatchlistItemRead[]
) {
  return buildUsWatchlistRows(group, items)[0] ?? null;
}

function mergeUsWatchlistRows(
  baseRows: USWatchlistRankingItemRead[],
  ranking: USWatchlistRankingRead | null
) {
  if (!ranking) return baseRows;

  const rankingBySymbol = new Map(
    ranking.results.map((row) => [row.symbol, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingBySymbol.get(row.symbol) ?? {}),
    rank: index + 1,
  }));
}

function WatchlistRankingPanel({
  groupName,
  lastUpdatedAt,
  rankBy,
  rankOptions,
  onRankByChange,
  onReload,
  reloadDisabled,
  secondaryAction,
  loadState,
  errorMessage,
  rows,
  summary,
  volumeHeader,
  emptyMessage,
}: {
  groupName: string | null;
  lastUpdatedAt: string | null;
  rankBy: string;
  rankOptions: RankingPanelOption[];
  onRankByChange: (value: string) => void;
  onReload: () => void;
  reloadDisabled: boolean;
  secondaryAction?: ReactNode;
  loadState: LoadState;
  errorMessage: string | null;
  rows: RankingDisplayRow[];
  summary: {
    stockCount: number;
    upCount: number;
    downCount: number;
  };
  volumeHeader: string;
  emptyMessage: string;
}) {
  return (
    <div className="space-y-4">
      <section className="border border-slate-200 bg-white">
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Selected Group
            </div>
            <h2 className="mt-1 text-2xl font-bold text-slate-950">
              {groupName ?? "尚未選擇分組"}
            </h2>
            <div className="mt-1 text-sm text-slate-500">
              {lastUpdatedAt ? `更新時間 ${lastUpdatedAt}` : "尚未載入分組資料"}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {secondaryAction}
            <select
              value={rankBy}
              onChange={(event) => onRankByChange(event.target.value)}
              className="h-9 border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 outline-none focus:border-red-700"
            >
              {rankOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={onReload}
              className="h-9 bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300"
              disabled={reloadDisabled}
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
            <div className="mt-1 text-xl font-bold">{rankLabel(rankBy)}</div>
          </div>
        </div>
      </section>

      <section className="border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <h3 className="text-sm font-bold text-slate-950">自選股列表</h3>
          <span className="text-xs text-slate-500">
            {loadState === "loading"
              ? "載入中"
              : rankBy === "none"
                ? `${rows.length} 檔 · 正常排序`
                : `${rows.length} 檔 · 依 ${rankLabel(rankBy)} 排序`}
          </span>
        </div>

        <div className="grid grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
          <span>名次</span>
          <span>股票</span>
          <span className="text-center">走勢</span>
          <span className="text-right">收盤</span>
          <span className="text-right">漲幅</span>
          <span className="text-right">漲跌</span>
          <span className="text-right">{volumeHeader}</span>
        </div>
        {rows.length > 0 ? (
          rows.map((row) => (
            <button
              key={row.key}
              type="button"
              onClick={row.onSelect}
              className={[
                "grid w-full grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] items-center border-t border-slate-200 px-4 py-2 text-left text-sm transition-colors",
                row.selected
                  ? "bg-slate-900 text-white"
                  : "bg-white text-slate-800 hover:bg-slate-50",
              ].join(" ")}
            >
              <span className={row.selected ? "text-slate-300" : "text-slate-500"}>
                #{row.rank}
              </span>
              <span className="min-w-0">
                <span className="block truncate font-semibold">
                  {row.symbol} {row.name ?? ""}
                </span>
                <span className={row.selected ? "block truncate text-xs text-slate-300" : "block truncate text-xs text-slate-500"}>
                  {row.meta ?? "-"}
                </span>
              </span>
              <span className="flex justify-center">{row.visual}</span>
              <span className="text-right font-semibold">
                <PriceUpdatePulse
                  value={row.closeValue}
                  direction={row.changePct}
                  resetKey={row.key}
                  className="justify-end tabular-nums"
                >
                  {row.close}
                </PriceUpdatePulse>
              </span>
              <span className={`text-right font-semibold ${row.selected ? "" : valueTone(row.changePct)}`}>
                <PriceUpdatePulse
                  value={row.change}
                  direction={row.changePct}
                  resetKey={row.key}
                  className="justify-end tabular-nums"
                >
                  {row.change}
                </PriceUpdatePulse>
              </span>
              <span className="text-right">
                <span
                  className={[
                    "px-2 py-1 text-xs font-semibold",
                    row.selected ? "bg-white text-slate-900" : trendClass(row.changePct),
                  ].join(" ")}
                >
                  {row.trend}
                </span>
              </span>
              <span className="text-right">
                <PriceUpdatePulse
                  value={row.volumeValue ?? row.volume}
                  direction={null}
                  resetKey={row.key}
                  className="justify-end tabular-nums"
                >
                  {row.volume}
                </PriceUpdatePulse>
              </span>
            </button>
          ))
        ) : (
          <div className="border-t border-slate-200 px-5 py-10 text-center text-sm text-slate-500">
            {loadState === "loading" ? "載入中" : emptyMessage}
          </div>
        )}
      </section>
    </div>
  );
}

export default function MarketDashboardClient({
  initialTree,
  initialItems,
  initialSelectedGroupId,
  initialChartData,
  initialIndicatorData,
  initialRankingData,
  initialMarketIndexSummary,
  initialUsWatchlistTree,
  initialUsWatchlistItems,
}: Props) {
  const initialSelectedGroup = useMemo(() => {
    const groups = flattenGroups(initialTree);
    return (
      groups.find((group) => group.id === initialSelectedGroupId) ??
      groups[0] ??
      null
    );
  }, [initialTree, initialSelectedGroupId]);
  const initialSelectedUsGroup = useMemo(() => {
    return flattenUsGroups(initialUsWatchlistTree)[0] ?? null;
  }, [initialUsWatchlistTree]);
  const initialSelectedUsRow = useMemo(() => {
    return firstUsWatchlistRow(initialSelectedUsGroup, initialUsWatchlistItems);
  }, [initialSelectedUsGroup, initialUsWatchlistItems]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(
    initialSelectedGroup?.id ?? null
  );
  const [selectedGroup, setSelectedGroup] = useState<WatchlistGroupNode | null>(
    initialSelectedGroup
  );
  const [selectedStockId, setSelectedStockId] = useState<string | null>(null);
  const [selectedStockName, setSelectedStockName] = useState<string | null>(null);
  const [watchlistTree, setWatchlistTree] = useState<WatchlistGroupNode[]>(initialTree);
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItemRead[]>(initialItems);
  const [activeMarket, setActiveMarket] = useState<MarketRegion>("tw");
  const [selectedUsSymbol, setSelectedUsSymbol] = useState<string | null>(
    initialSelectedUsRow?.symbol ?? null
  );
  const [selectedUsSecurityName, setSelectedUsSecurityName] = useState<string | null>(
    initialSelectedUsRow?.security_name ?? null
  );
  const [selectedUsGroupId, setSelectedUsGroupId] = useState<number | null>(
    initialSelectedUsGroup?.id ?? null
  );
  const [selectedUsGroup, setSelectedUsGroup] = useState<USWatchlistGroupNode | null>(
    initialSelectedUsGroup
  );
  const [selectedUsGroupName, setSelectedUsGroupName] = useState<string | null>(
    initialSelectedUsGroup?.group_name ?? null
  );
  const [usWatchlistTree, setUsWatchlistTree] =
    useState<USWatchlistGroupNode[]>(initialUsWatchlistTree);
  const [usWatchlistItems, setUsWatchlistItems] =
    useState<USWatchlistItemRead[]>(initialUsWatchlistItems);
  const [usWatchlistVersion, setUsWatchlistVersion] = useState(0);
  const [rankBy, setRankBy] = useState<RankBy>("none");
  const [ranking, setRanking] = useState<RankingResponse | null>(initialRankingData);
  const [usRankBy, setUsRankBy] = useState<USRankBy>("none");
  const [usRanking, setUsRanking] = useState<USWatchlistRankingRead | null>(null);
  const [marketIndexSummary, setMarketIndexSummary] =
    useState<MarketIndexSummary | null>(initialMarketIndexSummary);
  const [marketIndexLoadState, setMarketIndexLoadState] =
    useState<LoadState>(initialMarketIndexSummary ? "success" : "idle");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [usLoadState, setUsLoadState] = useState<LoadState>("idle");
  const [usUniverseRefreshState, setUsUniverseRefreshState] =
    useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [usErrorMessage, setUsErrorMessage] = useState<string | null>(null);
  const [usUniverseRefreshMessage, setUsUniverseRefreshMessage] =
    useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [usLastUpdatedAt, setUsLastUpdatedAt] = useState<string | null>(null);
  const dashboardRequestSeq = useRef(0);
  const usDashboardRequestSeq = useRef(0);
  const marketIndexRequestSeq = useRef(0);
  const finalDashboardRefreshDate = useRef<string | null>(null);
  const finalUsDashboardRefreshDate = useRef<string | null>(null);

  const activeGroupId = selectedGroupId ?? selectedGroup?.id ?? null;
  const activeGroupIdRef = useRef<number | null>(activeGroupId);
  const watchlistFreshnessRequestKeys = useRef<Set<string>>(new Set());
  const baseRows = useMemo(
    () => buildWatchlistRows(selectedGroup, watchlistItems),
    [selectedGroup, watchlistItems]
  );
  const rows = useMemo(() => {
    if (rankBy === "none") {
      return mergeWatchlistRows(baseRows, ranking);
    }

    return ranking?.results ?? baseRows;
  }, [baseRows, rankBy, ranking]);
  const summary = useMemo(() => {
    const upCount = rows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct > 0;
    }).length;
    const downCount = rows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct < 0;
    }).length;

    return {
      stockCount: baseRows.length,
      upCount,
      downCount,
    };
  }, [baseRows.length, rows]);
  const usBaseRows = useMemo(
    () => buildUsWatchlistRows(selectedUsGroup, usWatchlistItems),
    [selectedUsGroup, usWatchlistItems]
  );
  const usRows = useMemo(() => {
    if (usRankBy === "none") {
      return mergeUsWatchlistRows(usBaseRows, usRanking);
    }

    return usRanking?.results ?? usBaseRows;
  }, [usBaseRows, usRankBy, usRanking]);
  const usSummary = useMemo(() => {
    const upCount = usRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct > 0;
    }).length;
    const downCount = usRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct < 0;
    }).length;

    return {
      stockCount: usBaseRows.length,
      upCount,
      downCount,
    };
  }, [usBaseRows.length, usRows]);

  async function loadDashboard(
    groupId: number,
    currentRankBy = rankBy,
    options?: { silent?: boolean }
  ) {
    const requestSeq = dashboardRequestSeq.current + 1;
    dashboardRequestSeq.current = requestSeq;

    if (!options?.silent) {
      setLoadState("loading");
      setErrorMessage(null);
    }

    try {
      const marketState = getTaiwanMarketRefreshState();
      const commonParams = {
        include_children: true,
        enabled_only: true,
        ma_windows: "5,20,60",
        volume_ma_windows: "5,20",
      };

      const rankingData = await fetchJson<RankingResponse>(
        `/api/watchlists/groups/${groupId}/rankings/latest`,
        {
          ...commonParams,
          rank_by: currentRankBy === "none" ? "watchlist" : currentRankBy,
          sort_order: currentRankBy === "none" ? "asc" : "desc",
          limit: 100,
          volume_ratio_threshold: 1.5,
          use_intraday: marketState.isPollingWindow,
          intraday_limit: WATCHLIST_INTRADAY_LIMIT,
        }
      );

      if (dashboardRequestSeq.current !== requestSeq) return;

      setRanking(rankingData);
      setLastUpdatedAt(formatDashboardTime(new Date()));
      setLoadState("success");
    } catch (error) {
      if (dashboardRequestSeq.current !== requestSeq) return;

      setLoadState("error");
      setErrorMessage(error instanceof Error ? error.message : "資料讀取失敗");
    }
  }

  async function loadUsDashboard(
    groupId: number,
    currentRankBy = usRankBy,
    options?: { silent?: boolean }
  ) {
    const requestSeq = usDashboardRequestSeq.current + 1;
    usDashboardRequestSeq.current = requestSeq;

    if (!options?.silent) {
      setUsLoadState("loading");
      setUsErrorMessage(null);
    }

    try {
      const marketState = getUsMarketRefreshState();
      const rankingData = await fetchJson<USWatchlistRankingRead>(
        "/api/us-market/watchlists/ranking",
        {
          group_id: groupId,
          include_children: true,
          enabled_only: true,
          rank_by: currentRankBy,
          sort_order: currentRankBy === "none" ? "asc" : "desc",
          use_intraday: marketState.isPollingWindow,
          intraday_limit: WATCHLIST_INTRADAY_LIMIT,
        }
      );

      if (usDashboardRequestSeq.current !== requestSeq) return;

      setUsRanking(rankingData);
      setUsLastUpdatedAt(formatDashboardTime(new Date()));
      setUsLoadState("success");
    } catch (error) {
      if (usDashboardRequestSeq.current !== requestSeq) return;

      setUsLoadState("error");
      setUsErrorMessage(error instanceof Error ? error.message : "US ranking load failed");
    }
  }

  async function loadMarketIndices(options?: { silent?: boolean }) {
    const requestSeq = marketIndexRequestSeq.current + 1;
    marketIndexRequestSeq.current = requestSeq;

    if (!options?.silent) {
      setMarketIndexLoadState("loading");
    }

    try {
      const summaryData = await fetchJson<MarketIndexSummary>("/api/market/indices/summary");

      if (marketIndexRequestSeq.current !== requestSeq) return;

      setMarketIndexSummary(summaryData);
      setMarketIndexLoadState("success");
    } catch {
      if (marketIndexRequestSeq.current !== requestSeq) return;

      setMarketIndexLoadState("error");
    }
  }

  async function refreshWatchlistDailyPricesOnOpen(groupId: number, currentRankBy: RankBy) {
    const marketState = getTaiwanMarketRefreshState();
    const includeToday = marketState.isDailyPriceReleased;
    const requestKey = `${groupId}:${marketState.dateKey}:${includeToday ? "today" : "latest"}`;

    if (watchlistFreshnessRequestKeys.current.has(requestKey)) return;

    watchlistFreshnessRequestKeys.current.add(requestKey);

    try {
      await requestBackfillJob(
        `/api/watchlists/groups/${groupId}/refresh-latest`,
        { method: "POST" },
        {
          lookback_days: 14,
          include_today: includeToday,
          include_children: true,
          enabled_only: true,
          sleep_seconds: 0.3,
          skip_existing_months: true,
        },
        {
          intervalMs: 1500,
          timeoutMs: 600000,
        }
      );

      if (activeGroupIdRef.current === groupId) {
        await loadDashboard(groupId, currentRankBy, { silent: true });
      }
    } catch (error) {
      console.warn("Watchlist daily price refresh failed.", error);
    }
  }

  useEffect(() => {
    activeGroupIdRef.current = activeGroupId;
  }, [activeGroupId]);

  useEffect(() => {
    if (activeMarket !== "tw") return;

    let disposed = false;
    let refreshTimer: number | undefined;

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getTaiwanMarketRefreshState();
      const delay = marketState.isPollingWindow
        ? TAIWAN_INTRADAY_REFRESH_MS
        : Math.min(marketState.msUntilNextPollingStart, 300_000);

      refreshTimer = window.setTimeout(() => {
        void loadMarketIndices({ silent: true }).finally(scheduleRefresh);
      }, delay);
    }

    const initialTimer = window.setTimeout(() => {
      void loadMarketIndices().finally(scheduleRefresh);
    }, 0);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, [activeMarket]);

  useEffect(() => {
    if (activeMarket !== "tw") return;
    if (activeGroupId === null) return;

    const groupId = activeGroupId;
    let disposed = false;
    let refreshTimer: number | undefined;

    function clearRefreshTimer() {
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
    }

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getTaiwanMarketRefreshState();

      if (marketState.isPollingWindow) {
        refreshTimer = window.setTimeout(() => {
          void loadDashboard(groupId, rankBy, { silent: true }).finally(scheduleRefresh);
        }, TAIWAN_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalDashboardRefreshDate.current !== marketState.dateKey
      ) {
        finalDashboardRefreshDate.current = marketState.dateKey;
        refreshTimer = window.setTimeout(() => {
          void loadDashboard(groupId, rankBy, { silent: true }).finally(scheduleRefresh);
        }, 0);
        return;
      }

      refreshTimer = window.setTimeout(
        scheduleRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    const initialTimer = window.setTimeout(() => {
      void loadDashboard(groupId, rankBy).finally(() => {
        const marketState = getTaiwanMarketRefreshState();

        if (marketState.isAfterClose) {
          finalDashboardRefreshDate.current = marketState.dateKey;
        }

        scheduleRefresh();
        void refreshWatchlistDailyPricesOnOpen(groupId, rankBy);
      });
    }, 120);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      clearRefreshTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeGroupId, activeMarket, rankBy]);

  useEffect(() => {
    if (activeMarket !== "us") return;
    if (selectedUsGroupId === null) return;

    const groupId = selectedUsGroupId;
    let disposed = false;
    let refreshTimer: number | undefined;

    function clearRefreshTimer() {
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
    }

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getUsMarketRefreshState();

      if (marketState.isPollingWindow) {
        refreshTimer = window.setTimeout(() => {
          void loadUsDashboard(groupId, usRankBy, { silent: true }).finally(scheduleRefresh);
        }, US_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalUsDashboardRefreshDate.current !== marketState.dateKey
      ) {
        finalUsDashboardRefreshDate.current = marketState.dateKey;
        refreshTimer = window.setTimeout(() => {
          void loadUsDashboard(groupId, usRankBy, { silent: true }).finally(scheduleRefresh);
        }, 0);
        return;
      }

      refreshTimer = window.setTimeout(
        scheduleRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    const initialTimer = window.setTimeout(() => {
      void loadUsDashboard(groupId, usRankBy).finally(() => {
        const marketState = getUsMarketRefreshState();

        if (marketState.isAfterClose) {
          finalUsDashboardRefreshDate.current = marketState.dateKey;
        }

        scheduleRefresh();
      });
    }, 120);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      clearRefreshTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMarket, selectedUsGroupId, usRankBy, usWatchlistVersion]);

  function handleSelectGroup(group: WatchlistGroupNode | null) {
    setSelectedGroup(group);
    setSelectedGroupId(group?.id ?? null);

    if (group !== null) {
      setSelectedStockId(null);
      setSelectedStockName(null);
      setRanking(null);
      setLoadState("idle");
      setErrorMessage(null);
    } else {
      setRanking(null);
    }
  }

  function handleSelectStock(stockId: string, stockName: string | null) {
    setSelectedStockId(stockId);
    setSelectedStockName(stockName);
  }

  function handleSelectUsGroup(group: USWatchlistGroupNode | null) {
    const firstRow = firstUsWatchlistRow(group, usWatchlistItems);

    setSelectedUsGroupId(group?.id ?? null);
    setSelectedUsGroup(group);
    setSelectedUsGroupName(group?.group_name ?? null);
    setSelectedUsSymbol(firstRow?.symbol ?? null);
    setSelectedUsSecurityName(firstRow?.security_name ?? null);
    setUsRanking(null);
    setUsLoadState("idle");
    setUsErrorMessage(null);
  }

  function ensureSelectedUsLeaf() {
    const fallbackGroup = selectedUsGroup ?? flattenUsGroups(usWatchlistTree)[0] ?? null;
    const firstRow = firstUsWatchlistRow(fallbackGroup, usWatchlistItems);

    if (fallbackGroup !== selectedUsGroup) {
      setSelectedUsGroup(fallbackGroup);
      setSelectedUsGroupId(fallbackGroup?.id ?? null);
      setSelectedUsGroupName(fallbackGroup?.group_name ?? null);
    }

    if (selectedUsSymbol === null) {
      setSelectedUsSymbol(firstRow?.symbol ?? null);
      setSelectedUsSecurityName(firstRow?.security_name ?? null);
    }
  }

  async function refreshSelectedUsUniverse() {
    if (selectedUsGroupId === null) return;

    setUsUniverseRefreshState("loading");
    setUsUniverseRefreshMessage("Queueing US data refresh.");

    try {
      const job = await requestBackfillJob(
        `/api/us-market/watchlists/groups/${selectedUsGroupId}/refresh-resources`,
        { method: "POST" },
        {
          include_children: true,
          enabled_only: true,
          include_daily: true,
          include_sec_facts: true,
          include_profile: true,
          include_actions: false,
          outputsize: "compact",
          adjusted: false,
          sleep_seconds: 12,
        },
        {
          intervalMs: 1500,
          timeoutMs: 1_800_000,
          onUpdate: (nextJob) => {
            setUsUniverseRefreshMessage(formatJobStatus(nextJob));
          },
        }
      );
      const result =
        job.result && typeof job.result === "object" && !Array.isArray(job.result)
          ? (job.result as Record<string, unknown>)
          : null;
      const symbolCount =
        typeof result?.symbol_count === "number" ? result.symbol_count : null;
      const errorCount =
        typeof result?.error_count === "number" ? result.error_count : null;

      setUsUniverseRefreshState("success");
      setUsUniverseRefreshMessage(
        `Completed${symbolCount !== null ? ` ${symbolCount} symbols` : ""}${
          errorCount ? `, ${errorCount} resource errors` : ""
        }.`
      );
      await loadUsDashboard(selectedUsGroupId, usRankBy, { silent: true });
    } catch (error) {
      setUsUniverseRefreshState("error");
      setUsUniverseRefreshMessage(
        error instanceof Error ? error.message : "US data refresh failed."
      );
    }
  }

  function handleRankByChange(value: RankBy) {
    setRankBy(value);
    setRanking(null);
    setLoadState("idle");
    setErrorMessage(null);
  }

  function handleUsRankByChange(value: string) {
    setUsRankBy(value as USRankBy);
    setUsRanking(null);
    setUsLoadState("idle");
    setUsErrorMessage(null);
  }

  function renderRankingRow(row: RankingItem) {
    const selected = row.stock_id === selectedStockId;

    return (
      <button
        key={row.stock_id}
        type="button"
        onClick={() => handleSelectStock(row.stock_id, row.stock_name)}
        className={[
          "grid w-full grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] items-center border-t border-slate-200 px-4 py-2 text-left text-sm",
          selected ? "bg-slate-900 text-white" : "bg-white text-slate-800 hover:bg-slate-50",
        ].join(" ")}
      >
        <span className={selected ? "text-slate-300" : "text-slate-500"}>#{row.rank}</span>
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            {row.stock_id} {row.stock_name ?? ""}
          </span>
          <span className={selected ? "block truncate text-xs text-slate-300" : "block truncate text-xs text-slate-500"}>
            {formatRowTime(row.time) ?? row.primary_signal_label ?? statusLabel(row.status)}
          </span>
        </span>
        <span className="flex justify-center">
          <RankingSparkline row={row} selected={selected} />
        </span>
        <span className="text-right font-semibold">
          <PriceUpdatePulse
            value={row.close}
            direction={row.change_pct}
            resetKey={`${activeGroupId ?? "all"}:${row.stock_id}`}
            className="justify-end tabular-nums"
          >
            {formatPrice(row.close)}
          </PriceUpdatePulse>
        </span>
        <span className={`text-right font-semibold ${selected ? "" : valueTone(row.change_pct)}`}>
          <PriceUpdatePulse
            value={row.change_pct}
            direction={row.change_pct}
            resetKey={`${activeGroupId ?? "all"}:${row.stock_id}`}
            className="justify-end tabular-nums"
          >
            {formatPct(row.change_pct)}
          </PriceUpdatePulse>
        </span>
        <span className="text-right">
          <span
            className={[
              "px-2 py-1 text-xs font-semibold",
              selected
                ? selectedTrendClass(row.limit_status)
                : trendClass(row.change_pct, row.limit_status),
            ].join(" ")}
          >
            {trendLabel(row.change_pct, row.limit_status)}
          </span>
        </span>
        <span className="text-right">
          <PriceUpdatePulse
            value={row.volume}
            direction={null}
            resetKey={`${activeGroupId ?? "all"}:${row.stock_id}`}
            className="justify-end tabular-nums"
          >
            {formatLots(row.volume)}
          </PriceUpdatePulse>
        </span>
      </button>
    );
  }

  const groupSummaryPanel = (
    <section className="border border-slate-200 bg-white">
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
            onChange={(event) => handleRankByChange(event.target.value as RankBy)}
            className="h-9 border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 outline-none focus:border-red-700"
          >
            <option value="none">正常排序</option>
            <option value="change_pct">漲幅</option>
            <option value="score">Score</option>
            <option value="volume">成交量</option>
          </select>
          <button
            type="button"
            onClick={() => {
              void loadMarketIndices({ silent: true });
              if (activeGroupId !== null) void loadDashboard(activeGroupId);
            }}
            className="h-9 bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300"
            disabled={activeGroupId === null || loadState === "loading"}
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
          <div className="mt-1 text-xl font-bold">
            {rankLabel(ranking?.rank_by ?? rankBy)}
          </div>
        </div>
      </div>
    </section>
  );

  const rankingPanel = (
    <div className="space-y-4">
      {groupSummaryPanel}
      <section className="border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <h3 className="text-sm font-bold text-slate-950">自選股列表</h3>
          <span className="text-xs text-slate-500">
            {loadState === "loading"
              ? "載入中"
              : rankBy === "none"
                ? `${rows.length} 檔 · 正常排序`
                : `${rows.length} 檔 · 依 ${rankLabel(ranking?.rank_by ?? rankBy)} 排序`}
          </span>
        </div>

        <div className="grid grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
          <span>名次</span>
          <span>股票</span>
          <span className="text-center">走勢</span>
          <span className="text-right">收盤</span>
          <span className="text-right">漲幅</span>
          <span className="text-right">漲跌</span>
          <span className="text-right">成交量(張)</span>
        </div>
        {rows.length > 0 ? (
          rows.map(renderRankingRow)
        ) : (
          <div className="border-t border-slate-200 px-5 py-10 text-center text-sm text-slate-500">
            尚無排行資料
          </div>
        )}
      </section>
    </div>
  );

  const usDisplayRows: RankingDisplayRow[] = usRows.map((row) => {
    const selected = row.symbol === selectedUsSymbol;

    return {
      key: `${row.group_id}-${row.symbol}`,
      rank: row.rank,
      symbol: row.symbol,
      name: row.security_name,
      meta: [
        row.time ? formatRowTime(row.time) : row.trade_date?.slice(0, 10),
        row.exchange,
        row.asset_type,
      ]
        .filter(Boolean)
        .join(" · ") || statusLabel(row.status),
      visual: (
        <USRankingSparkline row={row} selected={selected} />
      ),
      close: formatPrice(row.close),
      closeValue: row.close,
      change: formatPct(row.change_pct),
      changePct: row.change_pct,
      trend: trendLabel(row.change_pct),
      volume: formatWholeNumber(row.volume),
      volumeValue: row.volume,
      selected,
      onSelect: () => {
        setSelectedUsSymbol(row.symbol);
        setSelectedUsSecurityName(row.security_name);
      },
    };
  });
  const usRankingPanel = (
    <WatchlistRankingPanel
      groupName={selectedUsGroupName}
      lastUpdatedAt={usLastUpdatedAt}
      rankBy={usRanking?.rank_by ?? usRankBy}
      rankOptions={[
        { value: "none", label: "正常排序" },
        { value: "change_pct", label: "漲幅" },
        { value: "volume", label: "成交量" },
        { value: "close", label: "收盤價" },
      ]}
      onRankByChange={handleUsRankByChange}
      onReload={() => {
        if (selectedUsGroupId !== null) void loadUsDashboard(selectedUsGroupId);
      }}
      reloadDisabled={selectedUsGroupId === null || usLoadState === "loading"}
      secondaryAction={
        <div className="flex max-w-[220px] flex-col items-end gap-1">
          <button
            type="button"
            onClick={() => void refreshSelectedUsUniverse()}
            className="h-9 whitespace-nowrap border border-slate-900 bg-white px-3 text-xs font-semibold text-slate-900 hover:border-red-700 hover:text-red-700 disabled:border-slate-200 disabled:text-slate-400"
            disabled={
              selectedUsGroupId === null || usUniverseRefreshState === "loading"
            }
          >
            {usUniverseRefreshState === "loading" ? "Backfilling" : "Backfill Data"}
          </button>
          {usUniverseRefreshMessage ? (
            <span
              className={[
                "line-clamp-2 text-right text-[11px]",
                usUniverseRefreshState === "error"
                  ? "text-red-600"
                  : "text-slate-500",
              ].join(" ")}
            >
              {usUniverseRefreshMessage}
            </span>
          ) : null}
        </div>
      }
      loadState={usLoadState}
      errorMessage={usErrorMessage}
      rows={usDisplayRows}
      summary={usSummary}
      volumeHeader="成交量"
      emptyMessage="尚無美股自選資料"
    />
  );

  return (
    <main className="h-screen overflow-hidden bg-slate-100 text-slate-950">
      <div className="flex h-full min-w-[1180px] flex-col">
        <div className="flex min-h-0 flex-1">
          {activeMarket === "us" ? (
            <USWatchlistSidebar
              initialTree={usWatchlistTree}
              initialItems={usWatchlistItems}
              selectedMarket={activeMarket}
              selectedSymbol={selectedUsSymbol}
              onMarketChange={(market) => {
                setActiveMarket(market);
                setErrorMessage(null);
                setUsErrorMessage(null);
                if (market === "us") {
                  ensureSelectedUsLeaf();
                }
              }}
              onSelectGroup={handleSelectUsGroup}
              onSelectSymbol={(symbol, securityName) => {
                setSelectedUsSymbol(symbol);
                setSelectedUsSecurityName(securityName);
              }}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setUsWatchlistTree(nextTree);
                setUsWatchlistItems(nextItems);

                const nextSelectedGroup =
                  flattenUsGroups(nextTree).find((group) => group.id === selectedUsGroupId) ??
                  flattenUsGroups(nextTree)[0] ??
                  null;
                const rowsForNextGroup = buildUsWatchlistRows(nextSelectedGroup, nextItems);
                const selectedSymbolKey = selectedUsSymbol?.toUpperCase() ?? null;
                const nextSelectedRow =
                  rowsForNextGroup.find((row) => row.symbol === selectedSymbolKey) ??
                  rowsForNextGroup[0] ??
                  null;

                setSelectedUsGroup(nextSelectedGroup);
                setSelectedUsGroupId(nextSelectedGroup?.id ?? null);
                setSelectedUsGroupName(nextSelectedGroup?.group_name ?? null);

                if (
                  nextSelectedRow === null ||
                  selectedUsSymbol === null ||
                  nextSelectedRow.symbol !== selectedUsSymbol.toUpperCase() ||
                  nextSelectedRow.security_name !== selectedUsSecurityName
                ) {
                  setSelectedUsSymbol(nextSelectedRow?.symbol ?? null);
                  setSelectedUsSecurityName(nextSelectedRow?.security_name ?? null);
                }
              }}
              onChanged={() => setUsWatchlistVersion((version) => version + 1)}
            />
          ) : (
            <SidebarWatchlistExplorer
              initialTree={watchlistTree}
              initialItems={watchlistItems}
              selectedGroupId={activeGroupId}
              selectedStockId={selectedStockId}
              selectedMarket={activeMarket}
              onSelectGroup={handleSelectGroup}
              onSelectStock={handleSelectStock}
              onMarketChange={(market) => {
                setActiveMarket(market);
                setErrorMessage(null);
                if (market === "us") {
                  ensureSelectedUsLeaf();
                }
              }}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setWatchlistTree(nextTree);
                setWatchlistItems(nextItems);

                const nextSelectedGroup =
                  flattenGroups(nextTree).find((group) => group.id === activeGroupId) ?? null;

                if (nextSelectedGroup) {
                  setSelectedGroup(nextSelectedGroup);
                }
              }}
              onChanged={(nextGroupId) => {
                const groupId = nextGroupId === undefined ? activeGroupId : nextGroupId;
                if (groupId !== null) {
                  void loadDashboard(groupId);
                } else {
                  setRanking(null);
                }
              }}
            />
          )}

          <section className="min-w-0 flex-1 overflow-y-auto p-4">
            {activeMarket === "tw" ? (
              <>
                <MarketTape summary={marketIndexSummary} loadState={marketIndexLoadState} />

                <StockDetailPanel
                  stockId={selectedStockId}
                  stockName={selectedStockName}
                  initialChartData={initialChartData}
                  initialIndicatorData={initialIndicatorData}
                  watchlistRankingPanel={rankingPanel}
                  marketIndexSummary={marketIndexSummary}
                />
              </>
            ) : activeMarket === "us" ? (
              <USStockDetailPanel
                selectedSymbol={selectedUsSymbol}
                selectedSecurityName={selectedUsSecurityName}
                watchlistRankingPanel={usRankingPanel}
              />
            ) : (
              <section className="border border-slate-200 bg-white px-5 py-10 text-sm text-slate-500">
                尚未啟用
              </section>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

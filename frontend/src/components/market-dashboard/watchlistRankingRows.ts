import type {
  JPWatchlistGroupNode,
  JPWatchlistItemRead,
  JPWatchlistRankingItemRead,
  JPWatchlistRankingRead,
  KRWatchlistGroupNode,
  KRWatchlistItemRead,
  KRWatchlistRankingItemRead,
  KRWatchlistRankingRead,
  RankingBatchResponse,
  RankingItem,
  RankingResponse,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  USWatchlistRankingItemRead,
  USWatchlistRankingRead,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";

export function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
}

export function flattenUsGroups(
  nodes: USWatchlistGroupNode[]
): USWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenUsGroups(node.children)]);
}

export function flattenJpGroups(
  nodes: JPWatchlistGroupNode[]
): JPWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenJpGroups(node.children)]);
}

export function flattenKrGroups(
  nodes: KRWatchlistGroupNode[]
): KRWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenKrGroups(node.children)]);
}

export function buildWatchlistRows(
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
        indicator_snapshot: {},
        context_snapshot: {},
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

export function mergeWatchlistRows(
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

function rankingRowDateKey(value: string | null | undefined) {
  return value?.slice(0, 10) ?? null;
}

function latestRankingTradeDate(rows: RankingItem[]) {
  return rows.reduce<string | null>((latest, row) => {
    const value = rankingRowDateKey(row.time);
    if (!value) return latest;
    return latest === null || value > latest ? value : latest;
  }, null);
}

export function mergeRankingBatchRows(
  currentRows: RankingItem[],
  batchRows: RankingItem[]
) {
  const rowsByStockId = new Map(currentRows.map((row) => [row.stock_id, row]));

  batchRows.forEach((row) => {
    rowsByStockId.set(row.stock_id, row);
  });

  return Array.from(rowsByStockId.values()).sort((a, b) => a.rank - b.rank);
}

function deferRankingTrendData(row: RankingItem): RankingItem {
  const intradayPoints = Array.isArray(row.intraday_points) ? row.intraday_points : [];

  if (intradayPoints.length === 0 && row.intraday_previous_close === null) {
    return row;
  }

  return {
    ...row,
    intraday_previous_close: null,
    intraday_points: [],
  };
}

export function buildProgressiveRankingResponse({
  batch,
  rows,
  currentStockCount,
  staleStockCount,
  noDataCount,
  errorCount,
  complete,
  deferTrendData,
}: {
  batch: RankingBatchResponse;
  rows: RankingItem[];
  currentStockCount: number;
  staleStockCount: number;
  noDataCount: number;
  errorCount: number;
  complete: boolean;
  deferTrendData?: boolean;
}): RankingResponse {
  return {
    group_id: batch.group_id,
    include_children: batch.include_children,
    rank_by: batch.rank_by,
    sort_order: batch.sort_order,
    requested_stock_count: batch.total_stock_count,
    ranked_count: rows.length,
    no_data_count: noDataCount,
    error_count: errorCount,
    trade_date: latestRankingTradeDate(rows),
    target_trade_date: batch.target_trade_date,
    is_current: complete ? staleStockCount === 0 : true,
    current_stock_count: currentStockCount,
    stale_stock_count: complete ? staleStockCount : 0,
    results: deferTrendData ? rows.map(deferRankingTrendData) : rows,
  };
}

export function buildUsWatchlistRows(
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
        session: "regular",
        has_extended_hours: false,
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

export function mergeUsWatchlistRows(
  baseRows: USWatchlistRankingItemRead[],
  ranking: USWatchlistRankingRead | null
) {
  if (!ranking) return baseRows;

  const rankingResults = Array.isArray(ranking.results) ? ranking.results : [];
  const rankingBySymbol = new Map(
    rankingResults.map((row) => [row.symbol, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingBySymbol.get(row.symbol) ?? {}),
    rank: index + 1,
  }));
}

export function buildJpWatchlistRows(
  group: JPWatchlistGroupNode | null,
  items: JPWatchlistItemRead[]
): JPWatchlistRankingItemRead[] {
  if (!group) return [];

  const itemsByGroupId = new Map<number, JPWatchlistItemRead[]>();
  const seenSymbols = new Set<string>();
  const rows: JPWatchlistRankingItemRead[] = [];

  items.forEach((item) => {
    if (!item.enabled) return;

    const groupItems = itemsByGroupId.get(item.group_id) ?? [];
    groupItems.push(item);
    itemsByGroupId.set(item.group_id, groupItems);
  });

  function appendGroupRows(currentGroup: JPWatchlistGroupNode) {
    (itemsByGroupId.get(currentGroup.id) ?? []).forEach((item) => {
      const symbol = item.symbol.toUpperCase();
      if (seenSymbols.has(symbol)) return;

      seenSymbols.add(symbol);
      rows.push({
        rank: rows.length + 1,
        symbol,
        security_name: item.security_name,
        exchange: item.exchange,
        market_segment: item.market_segment,
        sector_33_name: item.sector_33_name,
        asset_type: item.asset_type,
        group_id: item.group_id,
        trade_date: null,
        close: null,
        previous_close: null,
        change: null,
        change_pct: null,
        volume: null,
        status: "pending",
        latest_fetched_at: null,
        freshness_status: "missing",
        source: null,
        error_message: null,
      });
    });

    currentGroup.children.forEach(appendGroupRows);
  }

  appendGroupRows(group);
  return rows;
}

export function mergeJpWatchlistRows(
  baseRows: JPWatchlistRankingItemRead[],
  ranking: JPWatchlistRankingRead | null
) {
  if (!ranking) return baseRows;

  const rankingResults = Array.isArray(ranking.results) ? ranking.results : [];
  const rankingBySymbol = new Map(
    rankingResults.map((row) => [row.symbol, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingBySymbol.get(row.symbol) ?? {}),
    rank: index + 1,
  }));
}

export function buildKrWatchlistRows(
  group: KRWatchlistGroupNode | null,
  items: KRWatchlistItemRead[]
): KRWatchlistRankingItemRead[] {
  if (!group) return [];

  const itemsByGroupId = new Map<number, KRWatchlistItemRead[]>();
  const seenSymbols = new Set<string>();
  const rows: KRWatchlistRankingItemRead[] = [];

  items.forEach((item) => {
    if (!item.enabled) return;

    const groupItems = itemsByGroupId.get(item.group_id) ?? [];
    groupItems.push(item);
    itemsByGroupId.set(item.group_id, groupItems);
  });

  function appendGroupRows(currentGroup: KRWatchlistGroupNode) {
    (itemsByGroupId.get(currentGroup.id) ?? []).forEach((item) => {
      const symbol = item.symbol.toUpperCase();
      if (seenSymbols.has(symbol)) return;

      seenSymbols.add(symbol);
      rows.push({
        rank: rows.length + 1,
        symbol,
        security_name: item.security_name ?? item.security_name_kr,
        exchange: item.exchange,
        market_segment: item.market_segment,
        sector: item.sector,
        industry: item.industry,
        asset_type: item.asset_type,
        group_id: item.group_id,
        trade_date: null,
        close: null,
        previous_close: null,
        change: null,
        change_pct: null,
        volume: null,
        status: "pending",
        source: null,
        error_message: null,
      });
    });

    currentGroup.children.forEach(appendGroupRows);
  }

  appendGroupRows(group);
  return rows;
}

export function mergeKrWatchlistRows(
  baseRows: KRWatchlistRankingItemRead[],
  ranking: KRWatchlistRankingRead | null
) {
  if (!ranking) return baseRows;

  const rankingResults = Array.isArray(ranking.results) ? ranking.results : [];
  const rankingBySymbol = new Map(
    rankingResults.map((row) => [row.symbol, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingBySymbol.get(row.symbol) ?? {}),
    rank: index + 1,
  }));
}

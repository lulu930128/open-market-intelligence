import type {
  DashboardRoute,
  MarketRegion,
} from "@/components/market-dashboard/selection/dashboardRoutes";
import { getJpMarketIndexConfig } from "@/lib/jpMarketIndices";
import { getKrMarketIndexConfig } from "@/lib/krMarketIndices";
import { getUsMarketIndexConfig } from "@/lib/usMarketIndices";
import type { CryptoBaseAsset } from "@/types/cryptoMarket";
import type {
  JPStockMasterRead,
  JPWatchlistGroupNode,
  JPWatchlistItemRead,
  KRStockMasterRead,
  KRWatchlistGroupNode,
  KRWatchlistItemRead,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";

type GroupNode<T> = { children: T[] };

export type MarketSelectionData = {
  taiwanTree: WatchlistGroupNode[];
  taiwanItems: WatchlistItemRead[];
  usTree: USWatchlistGroupNode[];
  usItems: USWatchlistItemRead[];
  jpTree: JPWatchlistGroupNode[];
  jpItems: JPWatchlistItemRead[];
  krTree: KRWatchlistGroupNode[];
  krItems: KRWatchlistItemRead[];
};

export type InitialMarketSelectionOptions = MarketSelectionData & {
  initialMarket: MarketRegion;
  initialSelectedGroupId: number | null;
  initialSelectedStockId: string | null;
  initialSelectedStockName: string | null;
  initialSelectedFuturesSymbol: string | null;
  initialSelectedUsSymbol: string | null;
  initialSelectedUsSecurityName: string | null;
  initialSelectedJpSymbol: string | null;
  initialSelectedKrSymbol: string | null;
};

export type MarketSelectionState = {
  activeMarket: MarketRegion;
  taiwan: {
    groupId: number | null;
    group: WatchlistGroupNode | null;
    stockId: string | null;
    stockName: string | null;
    market: string | null;
    instrumentType: string;
    futuresSymbol: string | null;
  };
  us: {
    groupId: number | null;
    group: USWatchlistGroupNode | null;
    groupName: string | null;
    symbol: string | null;
    securityName: string | null;
  };
  jp: {
    groupId: number | null;
    group: JPWatchlistGroupNode | null;
    groupName: string | null;
    symbol: string | null;
    stock: JPStockMasterRead | null;
  };
  kr: {
    groupId: number | null;
    group: KRWatchlistGroupNode | null;
    groupName: string | null;
    symbol: string | null;
    stock: KRStockMasterRead | null;
  };
  crypto: {
    base: CryptoBaseAsset;
    instrumentKey: string | null;
    resourceInstrumentKey: string | null;
  };
};

function flattenGroupNodes<T extends GroupNode<T>>(nodes: T[]): T[] {
  return nodes.flatMap((node) => [node, ...flattenGroupNodes(node.children)]);
}

export function resolveInitialGroup<T extends GroupNode<T> & { id: number }>(
  tree: T[],
  requestedGroupId: number | null
) {
  const groups = flattenGroupNodes(tree);
  return groups.find((group) => group.id === requestedGroupId) ?? groups[0] ?? null;
}

function initialGroupId<T extends { id: number }>(
  group: T | null,
  requestedGroupId: number | null,
  initialMarket: MarketRegion,
  market: MarketRegion
) {
  if (group) return group.id;

  // Preserve the active route intent while server-rendered bootstrap data is
  // unavailable. The client-side explorer can then reconcile the requested
  // group after its recovery fetch succeeds instead of falling back to an
  // unselected dashboard.
  return initialMarket === market ? requestedGroupId : null;
}

function resolveRouteGroup<T extends GroupNode<T> & { id: number }>(
  tree: T[],
  requestedGroupId: number | null,
  currentGroup: T | null
) {
  const groups = flattenGroupNodes(tree);

  if (requestedGroupId !== null) {
    return groups.find((group) => group.id === requestedGroupId) ?? groups[0] ?? null;
  }

  return (
    groups.find((group) => group.id === currentGroup?.id) ??
    currentGroup ??
    groups[0] ??
    null
  );
}

export function normalizeSelectionSymbol(symbol: string) {
  return symbol.trim().toUpperCase();
}

export function jpStockForSelection(
  symbol: string,
  securityName: string | null,
  current: JPStockMasterRead | null
) {
  if (current?.symbol === symbol && current.security_name === securityName) return current;

  const indexConfig = getJpMarketIndexConfig(symbol);
  return {
    id: 0,
    symbol,
    local_code: null,
    security_name: indexConfig?.name ?? securityName,
    exchange: indexConfig?.exchange ?? null,
    market_segment: null,
    sector_33_code: null,
    sector_33_name: null,
    sector_17_code: null,
    sector_17_name: null,
    size_code: null,
    size_name: null,
    asset_type: indexConfig ? "index" : "stock",
    listing_source: indexConfig ? "market_index_config" : "watchlist",
    currency: "JPY",
    exchange_timezone_name: null,
    is_active: true,
    first_seen_at: "",
    last_seen_at: "",
    created_at: "",
    updated_at: "",
  } satisfies JPStockMasterRead;
}

export function krStockForSelection(
  symbol: string,
  securityName: string | null,
  current: KRStockMasterRead | null
) {
  const indexConfig = getKrMarketIndexConfig(symbol);
  const resolvedSymbol = indexConfig?.symbol ?? symbol;
  if (current?.symbol === resolvedSymbol && current.security_name === securityName) {
    return current;
  }

  return {
    id: 0,
    symbol: resolvedSymbol,
    local_code: indexConfig?.indexId ?? null,
    security_name: indexConfig?.name ?? securityName,
    security_name_kr: indexConfig?.nameKr ?? null,
    exchange: indexConfig?.exchange ?? null,
    market_segment: indexConfig?.marketSegment ?? null,
    sector: null,
    industry: null,
    asset_type: indexConfig ? "index" : "stock",
    listing_source: indexConfig ? "market_index_config" : "watchlist",
    currency: "KRW",
    exchange_timezone_name: "Asia/Seoul",
    is_active: true,
    first_seen_at: "",
    last_seen_at: "",
    created_at: "",
    updated_at: "",
  } satisfies KRStockMasterRead;
}

export function createInitialMarketSelection(
  options: InitialMarketSelectionOptions
): MarketSelectionState {
  const taiwanGroup = resolveInitialGroup(
    options.taiwanTree,
    options.initialSelectedGroupId
  );
  const usGroup = resolveInitialGroup(options.usTree, options.initialSelectedGroupId);
  const jpGroup = resolveInitialGroup(options.jpTree, options.initialSelectedGroupId);
  const krGroup = resolveInitialGroup(options.krTree, options.initialSelectedGroupId);
  const initialTaiwanItem = options.initialSelectedStockId
    ? options.taiwanItems.find(
        (item) => item.stock_id === options.initialSelectedStockId
      ) ?? null
    : null;

  return {
    activeMarket: options.initialMarket,
    taiwan: {
      groupId: initialGroupId(
        taiwanGroup,
        options.initialSelectedGroupId,
        options.initialMarket,
        "tw"
      ),
      group: taiwanGroup,
      stockId: options.initialSelectedStockId,
      stockName: options.initialSelectedStockName,
      market: initialTaiwanItem?.market ?? null,
      instrumentType: initialTaiwanItem?.instrument_type ?? "unknown",
      futuresSymbol: options.initialSelectedFuturesSymbol,
    },
    us: {
      groupId: initialGroupId(
        usGroup,
        options.initialSelectedGroupId,
        options.initialMarket,
        "us"
      ),
      group: usGroup,
      groupName: usGroup?.group_name ?? null,
      symbol: options.initialSelectedUsSymbol,
      securityName: options.initialSelectedUsSecurityName,
    },
    jp: {
      groupId: initialGroupId(
        jpGroup,
        options.initialSelectedGroupId,
        options.initialMarket,
        "jp"
      ),
      group: jpGroup,
      groupName: jpGroup?.group_name ?? null,
      symbol: options.initialSelectedJpSymbol,
      stock: null,
    },
    kr: {
      groupId: initialGroupId(
        krGroup,
        options.initialSelectedGroupId,
        options.initialMarket,
        "kr"
      ),
      group: krGroup,
      groupName: krGroup?.group_name ?? null,
      symbol: options.initialSelectedKrSymbol,
      stock: null,
    },
    crypto: {
      base: "BTC",
      instrumentKey: null,
      resourceInstrumentKey: null,
    },
  };
}

export function applyDashboardRoute(
  current: MarketSelectionState,
  route: DashboardRoute,
  data: MarketSelectionData
): MarketSelectionState {
  if (route.market === "tw") {
    const group = resolveRouteGroup(data.taiwanTree, route.groupId, current.taiwan.group);
    const stockItem = route.stockId
      ? data.taiwanItems.find((item) => item.stock_id === route.stockId) ?? null
      : null;

    return {
      ...current,
      activeMarket: "tw",
      taiwan: {
        groupId: initialGroupId(group, route.groupId, route.market, "tw"),
        group,
        stockId: route.futuresSymbol ? null : route.stockId,
        stockName:
          route.futuresSymbol || !route.stockId
            ? null
            : stockItem?.stock_name ??
              (current.taiwan.stockId === route.stockId ? current.taiwan.stockName : null),
        market:
          route.futuresSymbol || !route.stockId
            ? null
            : stockItem?.market ??
              (current.taiwan.stockId === route.stockId ? current.taiwan.market : null),
        instrumentType:
          route.futuresSymbol || !route.stockId
            ? "unknown"
            : stockItem?.instrument_type ??
              (current.taiwan.stockId === route.stockId
                ? current.taiwan.instrumentType
                : "unknown"),
        futuresSymbol: route.futuresSymbol,
      },
    };
  }

  if (route.market === "us") {
    const group = resolveRouteGroup(data.usTree, route.groupId, current.us.group);
    const symbol = route.symbol;
    const item = symbol
      ? data.usItems.find((candidate) => candidate.symbol.toUpperCase() === symbol) ?? null
      : null;
    const indexConfig = getUsMarketIndexConfig(symbol);

    return {
      ...current,
      activeMarket: "us",
      taiwan: { ...current.taiwan, futuresSymbol: null },
      us: {
        groupId: initialGroupId(group, route.groupId, route.market, "us"),
        group,
        groupName: group?.group_name ?? null,
        symbol,
        securityName:
          indexConfig?.name ??
          item?.security_name ??
          (current.us.symbol === symbol ? current.us.securityName : null),
      },
    };
  }

  if (route.market === "jp") {
    const group = resolveRouteGroup(data.jpTree, route.groupId, current.jp.group);
    const symbol = route.jpSymbol;
    const item = symbol
      ? data.jpItems.find((candidate) => candidate.symbol.toUpperCase() === symbol) ?? null
      : null;

    return {
      ...current,
      activeMarket: "jp",
      taiwan: { ...current.taiwan, futuresSymbol: null },
      jp: {
        groupId: initialGroupId(group, route.groupId, route.market, "jp"),
        group,
        groupName: group?.group_name ?? null,
        symbol,
        stock: symbol
          ? jpStockForSelection(symbol, item?.security_name ?? null, current.jp.stock)
          : null,
      },
    };
  }

  if (route.market === "kr") {
    const group = resolveRouteGroup(data.krTree, route.groupId, current.kr.group);
    const requestedSymbol = route.krSymbol;
    const item = requestedSymbol
      ? data.krItems.find(
          (candidate) => candidate.symbol.toUpperCase() === requestedSymbol
        ) ?? null
      : null;
    const stock = requestedSymbol
      ? krStockForSelection(
          requestedSymbol,
          item?.security_name ?? item?.security_name_kr ?? null,
          current.kr.stock
        )
      : null;

    return {
      ...current,
      activeMarket: "kr",
      taiwan: { ...current.taiwan, futuresSymbol: null },
      kr: {
        groupId: initialGroupId(group, route.groupId, route.market, "kr"),
        group,
        groupName: group?.group_name ?? null,
        symbol: stock?.symbol ?? requestedSymbol,
        stock,
      },
    };
  }

  return {
    ...current,
    activeMarket: "crypto",
    taiwan: { ...current.taiwan, futuresSymbol: null },
  };
}

export function reconcileTaiwanExplorerSelection(
  current: MarketSelectionState,
  tree: WatchlistGroupNode[],
  items: WatchlistItemRead[]
) {
  const group =
    flattenGroupNodes(tree).find((candidate) => candidate.id === current.taiwan.groupId) ??
    null;
  const item = current.taiwan.stockId
    ? items.find((candidate) => candidate.stock_id === current.taiwan.stockId) ?? null
    : null;
  return current.activeMarket === "tw" && group
    ? {
        ...current,
        taiwan: {
          ...current.taiwan,
          group,
          stockName: item?.stock_name ?? current.taiwan.stockName,
          market: item?.market ?? current.taiwan.market,
          instrumentType:
            item?.instrument_type ?? current.taiwan.instrumentType,
        },
      }
    : current;
}

export function reconcileUsExplorerSelection(
  current: MarketSelectionState,
  tree: USWatchlistGroupNode[],
  items: USWatchlistItemRead[]
) {
  const group = resolveRouteGroup(tree, current.us.groupId, current.us.group);
  const groupIds = group
    ? new Set(flattenGroupNodes([group]).map((candidate) => candidate.id))
    : new Set<number>();
  const symbol = current.us.symbol?.toUpperCase() ?? null;
  const row = symbol
    ? items.find(
        (item) =>
          item.enabled &&
          groupIds.has(item.group_id) &&
          item.symbol.toUpperCase() === symbol
      ) ?? null
    : null;
  const indexConfig = getUsMarketIndexConfig(symbol);

  return {
    ...current,
    us: {
      groupId: group?.id ?? null,
      group,
      groupName: group?.group_name ?? null,
      symbol: indexConfig?.symbol ?? (symbol && row ? symbol : null),
      securityName:
        indexConfig?.name ??
        row?.security_name ??
        (symbol === null ? current.us.securityName : null),
    },
  };
}

export function reconcileJpExplorerSelection(
  current: MarketSelectionState,
  tree: JPWatchlistGroupNode[],
  items: JPWatchlistItemRead[]
) {
  const group = resolveRouteGroup(tree, current.jp.groupId, current.jp.group);
  const symbol = current.jp.symbol?.toUpperCase() ?? null;
  const row = symbol
    ? items.find((item) => item.symbol.toUpperCase() === symbol) ?? null
    : null;
  const indexConfig = getJpMarketIndexConfig(symbol);
  const keepSymbol = symbol !== null && (row !== null || indexConfig !== null);

  return {
    ...current,
    jp: {
      groupId: group?.id ?? null,
      group,
      groupName: group?.group_name ?? null,
      symbol: keepSymbol ? symbol : null,
      stock: keepSymbol
        ? jpStockForSelection(
            symbol,
            indexConfig?.name ?? row?.security_name ?? null,
            current.jp.stock
          )
        : null,
    },
  };
}

export function reconcileKrExplorerSelection(
  current: MarketSelectionState,
  tree: KRWatchlistGroupNode[],
  items: KRWatchlistItemRead[]
) {
  const group = resolveRouteGroup(tree, current.kr.groupId, current.kr.group);
  const symbol = current.kr.symbol?.toUpperCase() ?? null;
  const row = symbol
    ? items.find((item) => item.symbol.toUpperCase() === symbol) ?? null
    : null;
  const indexConfig = getKrMarketIndexConfig(symbol);
  const keepSymbol = symbol !== null && (row !== null || indexConfig !== null);
  const stock = keepSymbol
    ? krStockForSelection(
        symbol,
        indexConfig?.name ?? row?.security_name ?? row?.security_name_kr ?? null,
        current.kr.stock
      )
    : null;

  return {
    ...current,
    kr: {
      groupId: group?.id ?? null,
      group,
      groupName: group?.group_name ?? null,
      symbol: stock?.symbol ?? null,
      stock,
    },
  };
}

"use client";

import JobStatusCenter from "@/components/JobStatusCenter";
import PortfolioHoldingsPanel from "@/components/PortfolioHoldingsPanel";
import SettingsDock from "@/components/SettingsDock";
import { marketLabel, marketSummary, useT, type TranslationFunction } from "@/i18n";
import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type { MarketRegion } from "@/components/market-dashboard/selection/dashboardRoutes";
import {
  CRYPTO_BASE_OPTIONS,
  CRYPTO_KLINE_INSTRUMENTS,
  buildCryptoKlineInstruments,
  cryptoBaseOptionsFromAssets,
  cryptoInstrumentsForBase,
  defaultCryptoInstrumentKeyForBase,
  normalizeCryptoBaseAsset,
  type CryptoBaseAsset,
  type CryptoKLineInstrument,
  type CryptoProviderContract,
} from "@/types/cryptoMarket";
import {
  RESOURCE_COMMODITY_GROUPS,
  RESOURCE_COMMODITY_INSTRUMENTS,
  resourceInstrumentByKey,
  resourceInstrumentsForGroup,
  type ResourceCommodityInstrument,
} from "@/types/resourceMarket";
import type {
  StockMasterRead,
  TaiwanFuturesQuote,
  WatchlistGroupNode,
  WatchlistGroupRead,
  WatchlistItemRead,
} from "@/types/market";
import {
  FormEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type Props = {
  initialTree: WatchlistGroupNode[];
  initialItems: WatchlistItemRead[];
  selectedGroupId: number | null;
  selectedStockId: string | null;
  selectedFuturesSymbol?: string | null;
  selectedMarket: MarketRegion;
  selectedCryptoBase?: CryptoBaseAsset;
  selectedCryptoInstrumentKey?: string | null;
  selectedResourceInstrumentKey?: string | null;
  onSelectGroup: (group: WatchlistGroupNode | null) => void;
  onSelectStock: (stockId: string, stockName: string | null) => void;
  onSelectFutures?: (symbol: string) => void;
  onSelectCryptoInstrument?: (base: CryptoBaseAsset, instrumentKey: string) => void;
  onSelectResourceInstrument?: (instrument: ResourceCommodityInstrument) => void;
  onMarketChange: (market: MarketRegion) => void;
  onExplorerDataChanged?: (
    tree: WatchlistGroupNode[],
    items: WatchlistItemRead[]
  ) => void;
  onChanged: (nextGroupId?: number | null) => Promise<void> | void;
};

type Message = { type: "success" | "error"; text: string } | null;
type DragPayload =
  | { type: "group"; groupId: number }
  | { type: "stock"; itemId: number; groupId: number; stockId: string };
type GroupDropPosition = "before" | "inside" | "after";
type DropTarget =
  | { type: "group"; groupId: number; position: GroupDropPosition }
  | { type: "stock"; itemId: number }
  | { type: "root" };
type PointerDragState = {
  payload: DragPayload;
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  active: boolean;
  target: DropTarget | null;
};
type CryptoWatchlistGroupNode = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  children: CryptoWatchlistGroupNode[];
};
type CryptoWatchlistItemRead = {
  id: number;
  group_id: number;
  asset: CryptoBaseAsset;
  asset_name: string | null;
  note: string | null;
  priority: number;
  tags: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

type SidebarMarketOption = {
  value: MarketRegion;
  enabled: boolean;
};

const sidebarMarketOptions: SidebarMarketOption[] = [
  { value: "tw", enabled: true },
  { value: "us", enabled: true },
  { value: "jp", enabled: true },
  { value: "kr", enabled: true },
  { value: "crypto", enabled: true },
];

function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
}

function findGroupById(
  nodes: WatchlistGroupNode[],
  groupId: number | null
): WatchlistGroupNode | null {
  if (groupId === null) return null;

  for (const node of nodes) {
    if (node.id === groupId) return node;

    const child = findGroupById(node.children, groupId);
    if (child) return child;
  }

  return null;
}

function flattenCryptoGroups(nodes: CryptoWatchlistGroupNode[]): CryptoWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenCryptoGroups(node.children)]);
}

function findCryptoGroupById(
  nodes: CryptoWatchlistGroupNode[],
  groupId: number | null
): CryptoWatchlistGroupNode | null {
  if (groupId === null) return null;

  for (const node of nodes) {
    if (node.id === groupId) return node;

    const child = findCryptoGroupById(node.children, groupId);
    if (child) return child;
  }

  return null;
}

function isKnownCryptoBaseAsset(
  value: string,
  baseOptions: readonly CryptoBaseAsset[]
): value is CryptoBaseAsset {
  const normalized = normalizeCryptoBaseAsset(value);
  return baseOptions.some((base) => normalizeCryptoBaseAsset(base) === normalized);
}

function isDescendantGroup(
  nodes: WatchlistGroupNode[],
  ancestorId: number,
  possibleDescendantId: number
) {
  const ancestor = findGroupById(nodes, ancestorId);
  if (!ancestor) return false;

  return flattenGroups(ancestor.children).some((group) => group.id === possibleDescendantId);
}

function inputClass() {
  return "h-9 w-full border border-omi-border bg-omi-surface px-3 text-sm text-omi-text outline-none transition focus:border-omi-accent";
}

function buttonClass(kind: "primary" | "ghost" | "danger" = "ghost") {
  if (kind === "primary") {
    return "h-8 border border-omi-accent-border bg-omi-accent-soft px-3 text-xs font-semibold text-omi-accent transition hover:border-omi-accent hover:bg-omi-surface-subtle hover:text-omi-accent-hover disabled:cursor-not-allowed disabled:border-omi-border-subtle disabled:bg-omi-surface-strong disabled:text-omi-text-subtle";
  }

  if (kind === "danger") {
    return "h-8 border border-omi-danger-border bg-omi-surface px-3 text-xs font-semibold text-omi-danger transition hover:bg-omi-danger-soft disabled:cursor-not-allowed disabled:border-omi-border-subtle disabled:text-omi-text-subtle";
  }

  return "h-8 bg-omi-surface-muted px-3 text-xs font-semibold text-omi-text-muted hover:bg-omi-surface-strong disabled:cursor-not-allowed disabled:text-omi-text-subtle";
}

const PINNED_INDEX_GROUP_NAME = "加權指數";
const PINNED_TAIWAN_FUTURES_SYMBOLS = ["TXF", "MXF", "TMF"] as const;
const PINNED_TAIWAN_FUTURES_REPRESENTATIVE = "TXF";
const PINNED_INDEX_ITEMS = [
  { kind: "index", stockId: "TAIEX", stockName: "加權指數", note: "TWSE" },
  { kind: "index", stockId: "TPEX", stockName: "櫃買指數", note: "TPEx" },
  {
    kind: "futures",
    symbol: PINNED_TAIWAN_FUTURES_REPRESENTATIVE,
    stockName: "台指期",
    note: "TXF / MXF / TMF",
  },
] as const;

function submitterValue(event: FormEvent<HTMLFormElement>) {
  const nativeEvent = event.nativeEvent as SubmitEvent;
  const submitter = nativeEvent.submitter as HTMLButtonElement | null;
  return submitter?.value ?? "";
}

function isNestedInteractiveTarget(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    target.closest("button,input,select,textarea,a,form") !== null
  );
}

function getSidebarMarketOption(value: MarketRegion) {
  return (
    sidebarMarketOptions.find((option) => option.value === value) ??
    sidebarMarketOptions[0]
  );
}

function SidebarMarketSummary({ selectedMarket }: { selectedMarket: MarketRegion }) {
  const t = useT();
  const option = getSidebarMarketOption(selectedMarket);

  return (
    <div className="flex min-h-0 flex-1 flex-col border-b border-omi-border-subtle px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
        {t("app.market")}
      </div>
      <div className="mt-1 text-lg font-bold text-omi-text-strong">{marketLabel(t, option.value)}</div>
      <div className="mt-2 border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3 text-sm font-semibold text-omi-text-muted">
        {marketSummary(t, option.value)}
      </div>
      {!option.enabled ? (
        <div className="mt-3 border border-omi-border-subtle bg-omi-surface px-3 py-3 text-xs text-omi-text-muted">
          {t("markets.reservedEntry")}
        </div>
      ) : null}
    </div>
  );
}

function resourceProviderStatusLabel(status: string, t: TranslationFunction) {
  if (status === "provider_pending" || status === "pending") {
    return t("crypto.sidebar.providerPending");
  }
  if (status === "best_effort_delayed" || status === "best_effort") {
    return t("crypto.sidebar.providerBestEffortDelayed");
  }
  return status.replaceAll("_", " ");
}

function SidebarCryptoControls({
  selectedBase,
  selectedInstrumentKey,
  selectedResourceInstrumentKey = null,
  onSelectInstrument,
  onSelectResourceInstrument,
}: {
  selectedBase: CryptoBaseAsset;
  selectedInstrumentKey?: string | null;
  selectedResourceInstrumentKey?: string | null;
  onSelectInstrument?: (base: CryptoBaseAsset, instrumentKey: string) => void;
  onSelectResourceInstrument?: (instrument: ResourceCommodityInstrument) => void;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(true);
  const [commodityExpanded, setCommodityExpanded] = useState(true);
  const [expandedCommodityGroups, setExpandedCommodityGroups] = useState<Set<string>>(
    () => new Set(RESOURCE_COMMODITY_GROUPS.map((group) => group.key))
  );
  const [currencyExpanded, setCurrencyExpanded] = useState(true);
  const [cryptoTree, setCryptoTree] = useState<CryptoWatchlistGroupNode[]>([]);
  const [cryptoItems, setCryptoItems] = useState<CryptoWatchlistItemRead[]>([]);
  const [expandedCryptoGroupIds, setExpandedCryptoGroupIds] = useState<Set<number>>(new Set());
  const [selectedCryptoGroupId, setSelectedCryptoGroupId] = useState<number | null>(null);
  const [cryptoLoading, setCryptoLoading] = useState(false);
  const [cryptoMessage, setCryptoMessage] = useState<Message>(null);
  const [cryptoGroupName, setCryptoGroupName] = useState("");
  const [cryptoRenameValue, setCryptoRenameValue] = useState("");
  const [cryptoAssetInput, setCryptoAssetInput] = useState("");
  const [cryptoNote, setCryptoNote] = useState("");
  const [cryptoTags, setCryptoTags] = useState("");
  const [cryptoAssetOptions, setCryptoAssetOptions] = useState<CryptoBaseAsset[]>(() =>
    CRYPTO_BASE_OPTIONS.map((asset) => normalizeCryptoBaseAsset(asset))
  );
  const [cryptoKlineInstruments, setCryptoKlineInstruments] =
    useState<CryptoKLineInstrument[]>(CRYPTO_KLINE_INSTRUMENTS);
  const currencyInstruments = useMemo(
    () => cryptoInstrumentsForBase("USDT", cryptoKlineInstruments),
    [cryptoKlineInstruments]
  );
  const activeInstrumentKey =
    selectedInstrumentKey ?? defaultCryptoInstrumentKeyForBase(selectedBase, cryptoKlineInstruments);
  const activeInstrument = cryptoInstrumentsForBase(
    selectedBase,
    cryptoKlineInstruments
  ).find(
    (instrument) => instrument.key === activeInstrumentKey
  );
  const selectedResourceInstrument = resourceInstrumentByKey(selectedResourceInstrumentKey);
  const cryptoItemsByGroupId = useMemo(() => {
    const map = new Map<number, CryptoWatchlistItemRead[]>();
    cryptoItems.forEach((item) => {
      const rows = map.get(item.group_id) ?? [];
      rows.push(item);
      map.set(item.group_id, rows);
    });
    return map;
  }, [cryptoItems]);

  function countCryptoGroupItems(node: CryptoWatchlistGroupNode): number {
    const directCount = cryptoItemsByGroupId.get(node.id)?.length ?? 0;
    return directCount + node.children.reduce((total, child) => total + countCryptoGroupItems(child), 0);
  }

  async function reloadCryptoWatchlist(nextSelectedGroupId?: number | null) {
    setCryptoLoading(true);
    try {
      const [treeResult, itemsResult, providerContractResult] = await Promise.allSettled([
        fetchJson<CryptoWatchlistGroupNode[]>("/api/crypto-market/watchlists/tree"),
        fetchJson<CryptoWatchlistItemRead[]>("/api/crypto-market/watchlists/items"),
        fetchJson<CryptoProviderContract>("/api/crypto-market/provider-contract"),
      ]);

      const failures = [
        treeResult.status === "rejected" ? "tree" : null,
        itemsResult.status === "rejected" ? "items" : null,
        providerContractResult.status === "rejected" ? "contract" : null,
      ].filter((value): value is string => Boolean(value));

      if (treeResult.status === "rejected" && itemsResult.status === "rejected") {
        throw treeResult.reason;
      }

      const nextTree = treeResult.status === "fulfilled" ? treeResult.value : cryptoTree;
      const nextItems = itemsResult.status === "fulfilled" ? itemsResult.value : cryptoItems;

      if (treeResult.status === "fulfilled") {
        setCryptoTree(nextTree);
      }
      if (itemsResult.status === "fulfilled") {
        setCryptoItems(nextItems);
      }
      if (providerContractResult.status === "fulfilled") {
        const nextProviderContract = providerContractResult.value;
        const nextAssetOptions = cryptoBaseOptionsFromAssets(nextProviderContract.assets);
        setCryptoAssetOptions(nextAssetOptions);
        setCryptoKlineInstruments(
          buildCryptoKlineInstruments(
            nextAssetOptions,
            nextProviderContract.assets,
            nextProviderContract.ohlcv_intervals
          )
        );
      }
      if (failures.length) {
        setCryptoMessage({
          type: "error",
          text: t("crypto.sidebar.watchlistLoadPartial", {
            resources: failures.join(", "),
          }),
        });
      }
      const flattened = flattenCryptoGroups(nextTree);
      const resolvedGroupId =
        nextSelectedGroupId !== undefined
          ? nextSelectedGroupId
          : selectedCryptoGroupId && flattened.some((group) => group.id === selectedCryptoGroupId)
            ? selectedCryptoGroupId
            : flattened[0]?.id ?? null;
      setSelectedCryptoGroupId(resolvedGroupId);
      if (resolvedGroupId !== null) {
        setExpandedCryptoGroupIds((previous) => new Set(previous).add(resolvedGroupId));
      }
      const selected = findCryptoGroupById(nextTree, resolvedGroupId);
      setCryptoRenameValue(selected?.group_name ?? "");
    } catch (error) {
      setCryptoMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("crypto.sidebar.watchlistLoadFailed"),
      });
    } finally {
      setCryptoLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void reloadCryptoWatchlist();
    }, 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggleCryptoGroup(groupId: number) {
    setExpandedCryptoGroupIds((previous) => {
      const next = new Set(previous);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }

  function selectCryptoGroup(group: CryptoWatchlistGroupNode) {
    setSelectedCryptoGroupId(group.id);
    setCryptoRenameValue(group.group_name);
    setExpandedCryptoGroupIds((previous) => new Set(previous).add(group.id));
  }

  function selectCryptoAsset(asset: CryptoBaseAsset) {
    const instrumentKey = defaultCryptoInstrumentKeyForBase(asset, cryptoKlineInstruments);
    onSelectInstrument?.(asset, instrumentKey);
  }

  const selectedCryptoGroup = findCryptoGroupById(cryptoTree, selectedCryptoGroupId);
  const selectedAssetLabel = selectedResourceInstrument
    ? `${selectedResourceInstrument.displayName} ${selectedResourceInstrument.symbol}`
    : activeInstrument?.symbol ?? selectedBase;
  const cryptoRootSelected =
    selectedResourceInstrumentKey === null &&
    cryptoItems.some((item) => item.asset === selectedBase);

  async function handleCryptoGroupSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const intent = submitterValue(event);
    const groupName = cryptoGroupName.trim();
    if (!groupName) return;
    setCryptoLoading(true);
    setCryptoMessage(null);
    try {
      const group = await requestJson<CryptoWatchlistGroupNode>(
        "/api/crypto-market/watchlists/groups",
        {
          method: "POST",
          body: JSON.stringify({
            group_name: groupName,
            parent_id: intent === "create_child" ? selectedCryptoGroupId : null,
          }),
        }
      );
      setCryptoGroupName("");
      await reloadCryptoWatchlist(group.id);
      setCryptoMessage({ type: "success", text: t("crypto.sidebar.watchlistSaved") });
    } catch (error) {
      setCryptoMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("crypto.sidebar.watchlistSaveFailed"),
      });
    } finally {
      setCryptoLoading(false);
    }
  }

  async function handleCryptoSelectedGroupSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedCryptoGroupId === null) return;
    const intent = submitterValue(event);
    setCryptoLoading(true);
    setCryptoMessage(null);
    try {
      if (intent === "delete") {
        await deleteRequest(`/api/crypto-market/watchlists/groups/${selectedCryptoGroupId}`, {
          recursive: true,
        });
        await reloadCryptoWatchlist(null);
      } else {
        const groupName = cryptoRenameValue.trim();
        if (!groupName) return;
        await requestJson<CryptoWatchlistGroupNode>(
          `/api/crypto-market/watchlists/groups/${selectedCryptoGroupId}`,
          {
            method: "PATCH",
            body: JSON.stringify({ group_name: groupName }),
          }
        );
        await reloadCryptoWatchlist(selectedCryptoGroupId);
      }
      setCryptoMessage({ type: "success", text: t("crypto.sidebar.watchlistSaved") });
    } catch (error) {
      setCryptoMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("crypto.sidebar.watchlistSaveFailed"),
      });
    } finally {
      setCryptoLoading(false);
    }
  }

  async function handleCryptoItemSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedCryptoGroupId === null) return;
    const asset = normalizeCryptoBaseAsset(cryptoAssetInput);
    if (!isKnownCryptoBaseAsset(asset, cryptoAssetOptions)) {
      setCryptoMessage({
        type: "error",
        text: t("crypto.sidebar.assetNotRegistered", { asset }),
      });
      return;
    }
    setCryptoLoading(true);
    setCryptoMessage(null);
    try {
      await requestJson<CryptoWatchlistItemRead>(
        "/api/crypto-market/watchlists/items",
        {
          method: "POST",
          body: JSON.stringify({
            group_id: selectedCryptoGroupId,
            asset,
            note: cryptoNote.trim() || null,
            tags: cryptoTags.trim() || null,
          }),
        }
      );
      setCryptoAssetInput("");
      setCryptoNote("");
      setCryptoTags("");
      await reloadCryptoWatchlist(selectedCryptoGroupId);
      selectCryptoAsset(asset);
      setCryptoMessage({ type: "success", text: t("crypto.sidebar.watchlistSaved") });
    } catch (error) {
      setCryptoMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("crypto.sidebar.watchlistSaveFailed"),
      });
    } finally {
      setCryptoLoading(false);
    }
  }

  async function deleteCryptoItem(item: CryptoWatchlistItemRead) {
    setCryptoLoading(true);
    setCryptoMessage(null);
    try {
      await deleteRequest(`/api/crypto-market/watchlists/items/${item.id}`);
      await reloadCryptoWatchlist(selectedCryptoGroupId);
    } catch (error) {
      setCryptoMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("crypto.sidebar.watchlistSaveFailed"),
      });
    } finally {
      setCryptoLoading(false);
    }
  }

  function renderCryptoGroupNode(node: CryptoWatchlistGroupNode, depth = 0) {
    const selected = selectedCryptoGroupId === node.id;
    const expandedNode = expandedCryptoGroupIds.has(node.id);
    const groupItems = cryptoItemsByGroupId.get(node.id) ?? [];
    const hasContent = node.children.length > 0 || groupItems.length > 0;
    const totalItemCount = countCryptoGroupItems(node);

    return (
      <div key={node.id}>
        <div
          className={[
            "relative flex cursor-pointer items-center gap-1 py-1 pr-1 text-sm",
            selected
              ? "omi-sidebar-selected text-omi-text-strong"
              : "text-omi-text-muted hover:bg-omi-surface-muted",
          ].join(" ")}
          style={{ paddingLeft: `${4 + depth * 16}px` }}
          onClick={() => selectCryptoGroup(node)}
        >
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              toggleCryptoGroup(node.id);
            }}
            className={[
              "h-6 w-4 text-xs",
              selected ? "text-omi-accent" : "text-omi-text-muted",
              !hasContent ? "opacity-40" : "",
            ].join(" ")}
          >
            {hasContent ? (expandedNode ? "v" : ">") : "-"}
          </button>
          <div className="min-w-0 flex-1 text-left">
            <div className="truncate font-semibold">{node.group_name}</div>
          </div>
          <span className={selected ? "pr-2 text-xs text-omi-accent" : "pr-2 text-xs text-omi-text-subtle"}>
            {totalItemCount}
          </span>
        </div>

        {expandedNode ? (
          <div>
            {groupItems.map((item) => {
              const itemSelected = selectedResourceInstrumentKey === null && selectedBase === item.asset;
              return (
                <div
                  key={item.id}
                  className={[
                    "group relative flex cursor-pointer items-center gap-1 py-1.5 pr-2 text-xs",
                    itemSelected
                      ? "omi-sidebar-selected text-omi-text-strong"
                      : item.enabled
                        ? "text-omi-text-muted hover:bg-omi-surface-muted"
                        : "text-omi-text-subtle",
                  ].join(" ")}
                  style={{ paddingLeft: `${24 + depth * 16}px` }}
                  onClick={() => selectCryptoAsset(item.asset)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold">
                      {item.asset}
                      {item.asset_name ? ` ${item.asset_name}` : ""}
                    </div>
                    {item.tags || item.note ? (
                      <div className={itemSelected ? "truncate text-omi-text-muted" : "truncate text-omi-text-subtle"}>
                        {item.tags || item.note}
                      </div>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className="hidden bg-omi-danger-soft px-1.5 py-0.5 text-[10px] font-semibold text-omi-danger group-hover:block"
                    onClick={(event) => {
                      event.stopPropagation();
                      void deleteCryptoItem(item);
                    }}
                  >
                    {t("common.deleteShort")}
                  </button>
                </div>
              );
            })}
            {node.children.map((child) => renderCryptoGroupNode(child, depth + 1))}
          </div>
        ) : null}
      </div>
    );
  }

  function toggleCommodityGroup(group: string) {
    setExpandedCommodityGroups((previous) => {
      const next = new Set(previous);
      if (next.has(group)) {
        next.delete(group);
      } else {
        next.add(group);
      }
      return next;
    });
  }

  return (
    <>
      <div className="flex items-center justify-between border-b border-omi-border-subtle px-4 py-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-omi-text-muted">
            {t("crypto.sidebar.header")}
          </div>
          <div className="truncate text-sm font-bold text-omi-text-strong">
            {selectedCryptoGroup?.group_name ?? t("crypto.sidebar.noWatchlistGroup")}
          </div>
          <div className="mt-1 truncate text-xs text-omi-text-muted">
            {selectedAssetLabel || t("crypto.sidebar.noSelection")}
          </div>
        </div>
        <div className="ml-3 flex shrink-0 flex-col gap-2">
          <button
            type="button"
            className={buttonClass("ghost")}
            onClick={() => void reloadCryptoWatchlist(selectedCryptoGroupId)}
            disabled={cryptoLoading}
          >
            {t("common.reload")}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        <div
          className={[
            "relative flex cursor-pointer items-center gap-1 py-1 pr-1 text-sm",
            cryptoRootSelected
              ? "omi-sidebar-selected text-omi-text-strong"
              : "text-omi-text-muted hover:bg-omi-surface-muted",
          ].join(" ")}
          style={{ paddingLeft: "4px" }}
          onClick={() => setExpanded((previous) => !previous)}
        >
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setExpanded((previous) => !previous);
            }}
            className={[
              "h-6 w-4 text-xs",
              cryptoRootSelected ? "text-omi-accent" : "text-omi-text-muted",
            ].join(" ")}
            aria-label={t("crypto.sidebar.aria.toggleCrypto")}
          >
            {expanded ? "v" : ">"}
          </button>

          <div className="min-w-0 flex-1 text-left">
            <div className="truncate font-semibold">{t("crypto.sidebar.crypto")}</div>
          </div>

          <span className={cryptoRootSelected ? "pr-2 text-xs text-omi-accent" : "pr-2 text-xs text-omi-text-subtle"}>
            {cryptoItems.length}
          </span>
        </div>

        {expanded ? (
          <div className="py-1">
            {cryptoTree.length > 0 ? (
              cryptoTree.map((node) => renderCryptoGroupNode(node))
            ) : (
              <div className="px-4 py-4 text-sm text-omi-text-muted">
                {t("crypto.sidebar.noWatchlistGroup")}
              </div>
            )}
          </div>
        ) : null}

        <div
          className="relative mt-3 flex cursor-pointer items-center gap-1 py-1 pr-1 text-sm text-omi-text-strong hover:bg-omi-surface-muted"
          style={{ paddingLeft: "4px" }}
          onClick={() => setCommodityExpanded((previous) => !previous)}
          data-testid="resource-sidebar-root-commodity"
        >
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setCommodityExpanded((previous) => !previous);
            }}
            className="h-6 w-4 text-xs text-omi-text-muted"
            aria-label={t("crypto.sidebar.aria.toggleCommodity")}
          >
            {commodityExpanded ? "v" : ">"}
          </button>

          <div className="min-w-0 flex-1 text-left">
            <div className="truncate font-semibold">{t("crypto.sidebar.commodity")}</div>
            <div className="truncate text-xs text-omi-text-subtle">
              {t("crypto.sidebar.commoditySubtitle")}
            </div>
          </div>

          <span className="pr-2 text-xs text-omi-text-subtle">
            {RESOURCE_COMMODITY_INSTRUMENTS.length + currencyInstruments.length}
          </span>
        </div>

        {commodityExpanded ? (
          <div>
            {RESOURCE_COMMODITY_GROUPS.map((group) => {
              const groupExpanded = expandedCommodityGroups.has(group.key);
              const instruments = resourceInstrumentsForGroup(group.key);

              return (
                <div key={group.key}>
                  <div
                    className="group relative flex w-full cursor-pointer items-center gap-1 py-1.5 pr-2 text-left text-sm text-omi-text-muted hover:bg-omi-surface-muted"
                    style={{ paddingLeft: "24px" }}
                    data-testid={`resource-sidebar-group-${group.key}`}
                    onClick={() => toggleCommodityGroup(group.key)}
                  >
                    <button
                      type="button"
                      className="h-5 w-4 text-xs text-omi-text-muted"
                      aria-label={t("crypto.sidebar.aria.toggleCommodityGroup", { label: group.label })}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggleCommodityGroup(group.key);
                      }}
                    >
                      {groupExpanded ? "v" : ">"}
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-semibold">{group.label}</div>
                    </div>
                    <span className="text-xs text-omi-text-subtle">{instruments.length}</span>
                  </div>

                  {groupExpanded ? (
                    <div>
                      {instruments.map((instrument) => (
                        <button
                          key={instrument.key}
                          type="button"
                          className={[
                            "group relative flex w-full cursor-pointer items-center gap-1 py-1.5 pr-2 text-left text-xs",
                            selectedResourceInstrumentKey === instrument.key
                              ? "omi-sidebar-selected text-omi-text-strong"
                              : "text-omi-text-muted hover:bg-omi-surface-muted",
                          ].join(" ")}
                          style={{ paddingLeft: "48px" }}
                          data-testid={`resource-sidebar-instrument-${instrument.symbol}`}
                          onClick={() => onSelectResourceInstrument?.(instrument)}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-xs font-semibold leading-4 text-omi-text-strong">
                              {instrument.displayName} {instrument.symbol}
                            </div>
                            <div
                              className={
                                selectedResourceInstrumentKey === instrument.key
                                  ? "truncate text-xs leading-4 text-omi-text-muted"
                                  : "truncate text-xs leading-4 text-omi-text-subtle"
                              }
                            >
                              {instrument.exchange} / {instrument.quoteAsset} /{" "}
                              {resourceProviderStatusLabel(instrument.providerStatus, t)}
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}

            <div>
              <div
                className="group relative flex w-full cursor-pointer items-center gap-1 py-1.5 pr-2 text-left text-sm text-omi-text-muted hover:bg-omi-surface-muted"
                style={{ paddingLeft: "24px" }}
                data-testid="resource-sidebar-group-currency"
                onClick={() => setCurrencyExpanded((previous) => !previous)}
              >
                <button
                  type="button"
                  className="h-5 w-4 text-xs text-omi-text-muted"
                  aria-label={t("crypto.sidebar.aria.toggleCurrency")}
                  onClick={(event) => {
                    event.stopPropagation();
                    setCurrencyExpanded((previous) => !previous);
                  }}
                >
                  {currencyExpanded ? "v" : ">"}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">{t("crypto.sidebar.currency")}</div>
                </div>
                <span className="text-xs text-omi-text-subtle">{currencyInstruments.length}</span>
              </div>

              {currencyExpanded ? (
                <div>
                  {currencyInstruments.map((instrument) => {
                    const instrumentSelected =
                      selectedResourceInstrumentKey === null &&
                      selectedBase === instrument.baseAsset &&
                      activeInstrumentKey === instrument.key;

                    return (
                      <button
                        key={instrument.key}
                        type="button"
                        className={[
                          "group relative flex w-full cursor-pointer items-center gap-1 py-1.5 pr-2 text-left text-xs",
                          instrumentSelected
                            ? "omi-sidebar-selected text-omi-text-strong"
                            : "text-omi-text-muted hover:bg-omi-surface-muted",
                        ].join(" ")}
                        style={{ paddingLeft: "48px" }}
                        data-testid={`currency-sidebar-instrument-${instrument.key}`}
                        onClick={() => onSelectInstrument?.(instrument.baseAsset, instrument.key)}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs font-semibold leading-4">{instrument.symbol}</div>
                          <div
                            className={
                              instrumentSelected
                                ? "truncate text-xs leading-4 text-omi-text-muted"
                                : "truncate text-xs leading-4 text-omi-text-subtle"
                            }
                          >
                            {instrument.exchange}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

      </div>

      {cryptoMessage ? (
        <div
          className={[
            "mx-4 mb-3 border px-3 py-2 text-xs",
            cryptoMessage.type === "success"
              ? "border-omi-market-down-border bg-omi-market-down-soft text-omi-market-down"
              : "border-omi-danger-border bg-omi-danger-soft text-omi-danger",
          ].join(" ")}
        >
          {cryptoMessage.text}
        </div>
      ) : null}

      <div className="border-b border-omi-border-subtle px-4 py-4">
        <JobStatusCenter placement="inline" market="crypto" />
      </div>

      <div className="space-y-4 p-4">
        <form onSubmit={handleCryptoGroupSubmit}>
          <div className="mb-2 text-xs font-bold text-omi-text-muted">{t("watchlist.groupManagement")}</div>
          <input
            className={inputClass()}
            name="group_name"
            placeholder={t("watchlist.addGroupPlaceholder")}
            value={cryptoGroupName}
            onChange={(event) => setCryptoGroupName(event.target.value)}
          />
          <div className="mt-2 flex gap-2">
            <button
              type="submit"
              name="intent"
              value="create_root"
              className={buttonClass("ghost")}
              disabled={cryptoLoading}
            >
              {t("common.addRoot")}
            </button>
            <button
              type="submit"
              name="intent"
              value="create_child"
              className={buttonClass("primary")}
              disabled={cryptoLoading || selectedCryptoGroupId === null}
            >
              {t("common.addChild")}
            </button>
          </div>
        </form>

        <form onSubmit={handleCryptoSelectedGroupSubmit} className="space-y-2">
          <input
            className={inputClass()}
            name="group_name"
            placeholder={t("watchlist.renameGroupPlaceholder")}
            value={cryptoRenameValue}
            onChange={(event) => setCryptoRenameValue(event.target.value)}
          />
          <div className="flex gap-2">
            <button
              type="submit"
              name="intent"
              value="rename"
              className={buttonClass("primary")}
              disabled={cryptoLoading || selectedCryptoGroupId === null}
            >
              {t("common.rename")}
            </button>
            <button
              type="submit"
              name="intent"
              value="delete"
              className={buttonClass("danger")}
              disabled={cryptoLoading || selectedCryptoGroupId === null}
            >
              {t("common.delete")}
            </button>
          </div>
        </form>

        <div className="space-y-2">
          <form
            id="crypto-watchlist-asset-form"
            action="/"
            method="post"
            onSubmit={handleCryptoItemSubmit}
            className="space-y-2"
          >
            <div className="text-xs font-bold text-omi-text-muted">{t("crypto.sidebar.addAsset")}</div>
            <input
              className={inputClass()}
              name="asset"
              placeholder={t("crypto.sidebar.assetInputPlaceholder")}
              value={cryptoAssetInput}
              onChange={(event) => setCryptoAssetInput(event.target.value.toUpperCase())}
              list="crypto-watchlist-asset-options"
            />
            <datalist id="crypto-watchlist-asset-options">
              {cryptoAssetOptions.map((asset) => (
                <option key={asset} value={asset} />
              ))}
            </datalist>
            <input
              className={inputClass()}
              name="note"
              placeholder={t("watchlist.notePlaceholder")}
              value={cryptoNote}
              onChange={(event) => setCryptoNote(event.target.value)}
            />
            <input
              className={inputClass()}
              name="tags"
              placeholder={t("watchlist.tagsPlaceholder")}
              value={cryptoTags}
              onChange={(event) => setCryptoTags(event.target.value)}
            />
          </form>
          <div className="flex items-center justify-between gap-2">
            <button
              type="submit"
              form="crypto-watchlist-asset-form"
              className={buttonClass("primary")}
              disabled={cryptoLoading || selectedCryptoGroupId === null}
            >
              {t("crypto.sidebar.addAssetButton")}
            </button>
            <SettingsDock placement="inline" />
          </div>
        </div>
      </div>
    </>
  );
}

export default function SidebarWatchlistExplorer({
  initialTree,
  initialItems,
  selectedGroupId,
  selectedStockId,
  selectedFuturesSymbol = null,
  selectedMarket,
  selectedCryptoBase = "BTC",
  selectedCryptoInstrumentKey = null,
  selectedResourceInstrumentKey = null,
  onSelectGroup,
  onSelectStock,
  onSelectFutures,
  onSelectCryptoInstrument,
  onSelectResourceInstrument,
  onMarketChange,
  onExplorerDataChanged,
  onChanged,
}: Props) {
  const t = useT();
  const [tree, setTree] = useState<WatchlistGroupNode[]>(initialTree);
  const [items, setItems] = useState<WatchlistItemRead[]>(initialItems);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [indexGroupExpanded, setIndexGroupExpanded] = useState(false);
  const [futuresQuotes, setFuturesQuotes] = useState<TaiwanFuturesQuote[]>([]);
  const [loading, setLoading] = useState(false);
  const [reloadingExplorerData, setReloadingExplorerData] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [folderName, setFolderName] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [stockInput, setStockInput] = useState("");
  const [stockNote, setStockNote] = useState("");
  const [stockTags, setStockTags] = useState("");
  const [stockSuggestions, setStockSuggestions] = useState<StockMasterRead[]>([]);
  const [dragPayload, setDragPayload] = useState<DragPayload | null>(null);
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);
  const [pointerDrag, setPointerDrag] = useState<PointerDragState | null>(null);
  const pointerDragRef = useRef<PointerDragState | null>(null);

  const allGroups = useMemo(() => flattenGroups(tree), [tree]);
  const selectedGroup = useMemo(() => {
    return allGroups.find((group) => group.id === selectedGroupId) ?? null;
  }, [allGroups, selectedGroupId]);
  const hasPointerDrag = pointerDrag !== null;
  const futuresQuotesBySymbol = useMemo(() => {
    return new Map(futuresQuotes.map((quote) => [quote.symbol, quote]));
  }, [futuresQuotes]);

  const itemsByGroupId = useMemo(() => {
    const map = new Map<number, WatchlistItemRead[]>();

    items.forEach((item) => {
      const list = map.get(item.group_id) ?? [];
      list.push(item);
      map.set(item.group_id, list);
    });

    return map;
  }, [items]);

  function countGroupItems(node: WatchlistGroupNode): number {
    const directCount = itemsByGroupId.get(node.id)?.length ?? 0;
    return (
      directCount +
      node.children.reduce((total, child) => total + countGroupItems(child), 0)
    );
  }

  function getSiblingGroups(parentId: number | null) {
    if (parentId === null) return tree;

    return findGroupById(tree, parentId)?.children ?? [];
  }

  function getNextSiblingGroupId(targetGroup: WatchlistGroupNode) {
    const siblings = getSiblingGroups(targetGroup.parent_id);
    const targetIndex = siblings.findIndex((group) => group.id === targetGroup.id);

    return targetIndex >= 0 ? siblings[targetIndex + 1]?.id ?? null : null;
  }

  async function reloadExplorerData(options?: { keepSelection?: boolean }) {
    const [treeData, itemData] = await Promise.all([
      fetchJson<WatchlistGroupNode[]>("/api/watchlists/tree"),
      fetchJson<WatchlistItemRead[]>("/api/watchlists/items", {
        limit: 5000,
        offset: 0,
      }),
    ]);

    setTree(treeData);
    setItems(itemData);
    onExplorerDataChanged?.(treeData, itemData);

    const flattened = flattenGroups(treeData);
    const selectedStillExists =
      selectedGroupId !== null &&
      flattened.some((group) => group.id === selectedGroupId);

    if (options?.keepSelection && selectedStillExists) {
      const currentGroup =
        flattened.find((group) => group.id === selectedGroupId) ?? null;
      setRenameValue(currentGroup?.group_name ?? "");
      setExpandedIds((previous) => {
        if (selectedGroupId === null) return previous;

        const next = new Set(previous);
        next.add(selectedGroupId);
        return next;
      });
      return currentGroup;
    }

    setRenameValue("");
    setExpandedIds(new Set());
    return null;
  }

  async function reloadSelectedGroupList() {
    setReloadingExplorerData(true);
    setMessage(null);

    try {
      const nextGroup = await reloadExplorerData({ keepSelection: true });
      await onChanged(nextGroup?.id ?? selectedGroupId);
      setMessage({ type: "success", text: t("watchlist.messages.reloadSuccess") });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("watchlist.messages.reloadError"),
      });
    } finally {
      setReloadingExplorerData(false);
    }
  }

  async function runAction(
    action: () => Promise<void>,
    successText: string,
    options?: { keepSelection?: boolean }
  ) {
    setLoading(true);
    setMessage(null);

    try {
      await action();
      const nextGroup = await reloadExplorerData({
        keepSelection: options?.keepSelection ?? true,
      });
      await onChanged(nextGroup?.id ?? null);
      setMessage({ type: "success", text: successText });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("watchlist.messages.actionError"),
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setTree(initialTree);
      setItems(initialItems);
      setExpandedIds(new Set());
    }, 0);

    return () => window.clearTimeout(timer);
  }, [initialTree, initialItems]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      reloadExplorerData({ keepSelection: selectedGroupId !== null }).catch((error) => {
        setMessage({
          type: "error",
          text: error instanceof Error ? error.message : t("watchlist.messages.readError"),
        });
      });
    }, 0);

    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedMarket !== "tw") return;

    let cancelled = false;
    const timer = window.setTimeout(() => {
      const loadQuotes = async () => {
        const autoRows = await fetchJson<TaiwanFuturesQuote[]>(
          "/api/market/tw-futures/latest",
          {
            symbols: PINNED_TAIWAN_FUTURES_SYMBOLS.join(","),
            refresh: true,
            session: "auto",
          }
        );

        if (autoRows.length > 0) return autoRows;

        return fetchJson<TaiwanFuturesQuote[]>("/api/market/tw-futures/latest", {
          symbols: PINNED_TAIWAN_FUTURES_SYMBOLS.join(","),
          refresh: true,
          session: "regular",
        });
      };

      loadQuotes()
        .then((rows) => {
          if (cancelled) return;
          setFuturesQuotes(rows);
        })
        .catch(() => {
          if (!cancelled) setFuturesQuotes([]);
        });
    }, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [selectedMarket]);

  useEffect(() => {
    const keyword = stockInput.trim();
    const timer = window.setTimeout(() => {
      if (keyword.length < 2) {
        setStockSuggestions([]);
        return;
      }

      fetchJson<StockMasterRead[]>("/api/stocks/search", {
        keyword,
        limit: 8,
      })
        .then(setStockSuggestions)
        .catch(() => setStockSuggestions([]));
    }, 180);

    return () => window.clearTimeout(timer);
  }, [stockInput]);

  function selectGroup(group: WatchlistGroupNode) {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      next.add(group.id);
      return next;
    });
    onSelectGroup(group);
    setRenameValue(group.group_name);
  }

  function toggleExpanded(groupId: number) {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }

  function getGroupDropPosition(
    targetElement: HTMLElement,
    clientY: number
  ): GroupDropPosition {
    const rect = targetElement.getBoundingClientRect();
    const y = clientY - rect.top;

    if (y < rect.height * 0.3) return "before";
    if (y > rect.height * 0.7) return "after";
    return "inside";
  }

  function setCurrentPointerDrag(next: PointerDragState | null) {
    pointerDragRef.current = next;
    setPointerDrag(next);
  }

  function getDragLabel(payload: DragPayload) {
    if (payload.type === "group") {
      return allGroups.find((group) => group.id === payload.groupId)?.group_name ?? t("watchlist.groupFallback");
    }

    const item = items.find((entry) => entry.id === payload.itemId);
    return item ? `${item.stock_id} ${item.stock_name ?? ""}`.trim() : payload.stockId;
  }

  function dropTargetKey(target: DropTarget | null, payload: DragPayload) {
    if (!target) return null;
    if (target.type === "root") return "root";
    if (target.type === "stock") return `stock:${target.itemId}:before`;

    const position = payload.type === "stock" ? "inside" : target.position;
    return `group:${target.groupId}:${position}`;
  }

  function clearPointerDrag() {
    setCurrentPointerDrag(null);
    setDragPayload(null);
    setDragOverKey(null);
  }

  function canDropGroupOnTarget(
    draggedGroupId: number,
    targetGroup: WatchlistGroupNode,
    position: GroupDropPosition
  ) {
    if (draggedGroupId === targetGroup.id) return false;

    const nextParentId = position === "inside" ? targetGroup.id : targetGroup.parent_id;

    if (nextParentId === draggedGroupId) return false;
    if (isDescendantGroup(tree, draggedGroupId, targetGroup.id)) return false;

    return true;
  }

  function resolvePointerDropTarget(
    clientX: number,
    clientY: number,
    payload: DragPayload
  ): DropTarget | null {
    const element = document.elementFromPoint(clientX, clientY) as HTMLElement | null;
    if (!element) return null;

    const stockElement = element.closest<HTMLElement>("[data-watchlist-stock-id]");
    if (stockElement && payload.type === "stock") {
      const itemId = Number(stockElement.dataset.watchlistStockId);
      if (Number.isFinite(itemId) && itemId !== payload.itemId) {
        return { type: "stock", itemId };
      }
    }

    const groupElement = element.closest<HTMLElement>("[data-watchlist-group-id]");
    if (groupElement) {
      const groupId = Number(groupElement.dataset.watchlistGroupId);
      const targetGroup = findGroupById(tree, Number.isFinite(groupId) ? groupId : null);
      if (!targetGroup) return null;

      const position =
        payload.type === "stock"
          ? "inside"
          : getGroupDropPosition(groupElement, clientY);

      if (
        payload.type === "group" &&
        !canDropGroupOnTarget(payload.groupId, targetGroup, position)
      ) {
        return null;
      }

      return { type: "group", groupId: targetGroup.id, position };
    }

    const rootElement = element.closest<HTMLElement>("[data-watchlist-root-drop='true']");
    if (rootElement && payload.type === "group") {
      return { type: "root" };
    }

    return null;
  }

  function beginPointerDrag(
    event: ReactPointerEvent<HTMLElement>,
    payload: DragPayload
  ) {
    if (event.button !== 0) return;

    event.preventDefault();
    event.stopPropagation();
    window.getSelection()?.removeAllRanges();

    const next = {
      payload,
      startX: event.clientX,
      startY: event.clientY,
      currentX: event.clientX,
      currentY: event.clientY,
      active: false,
      target: null,
    };

    setCurrentPointerDrag(next);
  }

  async function movePayloadToGroup(
    node: WatchlistGroupNode,
    position: GroupDropPosition,
    currentDrag: DragPayload | null
  ) {
    if (!currentDrag) return;

    if (currentDrag.type === "group") {
      const nextParentId = position === "inside" ? node.id : node.parent_id;
      const beforeGroupId =
        position === "before"
          ? node.id
          : position === "after"
            ? getNextSiblingGroupId(node)
            : null;

      await runAction(
        async () => {
          await requestJson<WatchlistGroupRead>(
            `/api/watchlists/groups/${currentDrag.groupId}/move`,
            {
              method: "POST",
              body: JSON.stringify({
                parent_id: nextParentId,
                before_group_id: beforeGroupId,
              }),
            }
          );
        },
        t("watchlist.messages.movedGroup"),
        { keepSelection: true }
      );
      return;
    }

    await runAction(
      async () => {
        await requestJson<WatchlistItemRead>(
          `/api/watchlists/items/${currentDrag.itemId}/move`,
          {
            method: "POST",
            body: JSON.stringify({
              group_id: node.id,
              before_item_id: null,
            }),
          }
        );
      },
      t("watchlist.messages.movedStock"),
      { keepSelection: true }
    );
  }

  async function movePayloadBeforeStock(
    item: WatchlistItemRead,
    currentDrag: DragPayload | null
  ) {
    if (!currentDrag || currentDrag.type !== "stock" || currentDrag.itemId === item.id) return;

    await runAction(
      async () => {
        await requestJson<WatchlistItemRead>(
          `/api/watchlists/items/${currentDrag.itemId}/move`,
          {
            method: "POST",
            body: JSON.stringify({
              group_id: item.group_id,
              before_item_id: item.id,
            }),
          }
        );
      },
      t("watchlist.messages.reorderedStock"),
      { keepSelection: true }
    );
  }

  async function movePayloadToRoot(currentDrag: DragPayload | null) {
    if (!currentDrag || currentDrag.type !== "group") return;

    await runAction(
      async () => {
        await requestJson<WatchlistGroupRead>(
          `/api/watchlists/groups/${currentDrag.groupId}/move`,
          {
            method: "POST",
            body: JSON.stringify({
              parent_id: null,
              before_group_id: null,
            }),
          }
        );
      },
      t("watchlist.messages.movedToRoot"),
      { keepSelection: true }
    );
  }

  async function applyDropTarget(payload: DragPayload, target: DropTarget) {
    if (target.type === "root") {
      await movePayloadToRoot(payload);
      return;
    }

    if (target.type === "group") {
      const targetGroup = findGroupById(tree, target.groupId);
      if (!targetGroup) return;

      await movePayloadToGroup(targetGroup, target.position, payload);
      return;
    }

    if (payload.type !== "stock") return;

    const targetItem = items.find((item) => item.id === target.itemId);
    if (!targetItem) return;

    await movePayloadBeforeStock(targetItem, payload);
  }

  useEffect(() => {
    if (!hasPointerDrag) return;

    function handlePointerMove(event: PointerEvent) {
      const current = pointerDragRef.current;
      if (!current) return;

      const moved =
        current.active ||
        Math.abs(event.clientX - current.startX) > 4 ||
        Math.abs(event.clientY - current.startY) > 4;
      const target = moved
        ? resolvePointerDropTarget(event.clientX, event.clientY, current.payload)
        : null;
      const next = {
        ...current,
        currentX: event.clientX,
        currentY: event.clientY,
        active: moved,
        target,
      };

      setCurrentPointerDrag(next);
      setDragPayload(moved ? current.payload : null);
      setDragOverKey(dropTargetKey(target, current.payload));
    }

    function handlePointerUp() {
      const current = pointerDragRef.current;
      clearPointerDrag();

      if (current?.active && current.target) {
        void applyDropTarget(current.payload, current.target);
      }
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasPointerDrag]);

  async function createRootFolder() {
    const name = folderName.trim();
    if (!name) {
      setMessage({ type: "error", text: t("watchlist.messages.groupNameRequired") });
      return;
    }

    await runAction(
      async () => {
        await requestJson<WatchlistGroupRead>("/api/watchlists/groups", {
          method: "POST",
          body: JSON.stringify({
            parent_id: null,
            group_name: name,
            description: null,
            sort_order: 100,
            is_active: true,
          }),
        });
        setFolderName("");
      },
      t("watchlist.messages.createdGroup"),
      { keepSelection: false }
    );
  }

  async function createChildFolder() {
    const name = folderName.trim();
    if (selectedGroupId === null) {
      setMessage({ type: "error", text: t("watchlist.messages.selectGroup") });
      return;
    }
    if (!name) {
      setMessage({ type: "error", text: t("watchlist.messages.groupNameRequired") });
      return;
    }

    await runAction(
      async () => {
        await requestJson<WatchlistGroupRead>("/api/watchlists/groups", {
          method: "POST",
          body: JSON.stringify({
            parent_id: selectedGroupId,
            group_name: name,
            description: null,
            sort_order: 100,
            is_active: true,
          }),
        });
        setFolderName("");
      },
      t("watchlist.messages.createdChildGroup"),
      { keepSelection: true }
    );
  }

  async function renameSelectedFolder() {
    const name = renameValue.trim();
    if (selectedGroupId === null || !selectedGroup) {
      setMessage({ type: "error", text: t("watchlist.messages.selectGroup") });
      return;
    }
    if (!name) {
      setMessage({ type: "error", text: t("watchlist.messages.newNameRequired") });
      return;
    }
    if (name === selectedGroup.group_name) return;

    await runAction(
      async () => {
        await requestJson<WatchlistGroupRead>(
          `/api/watchlists/groups/${selectedGroupId}`,
          {
            method: "PATCH",
            body: JSON.stringify({ group_name: name }),
          }
        );
      },
      t("watchlist.messages.renamedGroup"),
      { keepSelection: true }
    );
  }

  async function deleteSelectedFolder() {
    if (selectedGroupId === null || !selectedGroup) {
      setMessage({ type: "error", text: t("watchlist.messages.selectGroup") });
      return;
    }

    const confirmed = window.confirm(
      t("watchlist.messages.confirmDeleteGroup", {
        groupName: selectedGroup.group_name,
      })
    );
    if (!confirmed) return;

    await runAction(
      async () => {
        await deleteRequest(`/api/watchlists/groups/${selectedGroupId}`, {
          recursive: true,
        });
      },
      t("watchlist.messages.deletedGroup"),
      { keepSelection: false }
    );
  }

  async function createStockItem() {
    const value = stockInput.trim().toUpperCase();
    if (selectedGroupId === null) {
      setMessage({ type: "error", text: t("watchlist.messages.selectGroup") });
      return;
    }
    if (!value) {
      setMessage({ type: "error", text: t("watchlist.messages.stockIdRequired") });
      return;
    }

    await runAction(
      async () => {
        await requestJson<WatchlistItemRead>("/api/watchlists/items", {
          method: "POST",
          body: JSON.stringify({
            group_id: selectedGroupId,
            stock_id: value,
            note: stockNote.trim() || null,
            priority: 100,
            tags: stockTags.trim() || null,
            enabled: true,
          }),
        });
        setStockInput("");
        setStockNote("");
        setStockTags("");
        setStockSuggestions([]);
      },
      t("watchlist.messages.addedStock"),
      { keepSelection: true }
    );
  }

  async function deleteStockItem(item: WatchlistItemRead) {
    const confirmed = window.confirm(
      t("watchlist.messages.confirmDeleteStock", {
        stockId: item.stock_id,
        stockName: item.stock_name ?? "",
      })
    );
    if (!confirmed) return;

    await runAction(
      async () => {
        await deleteRequest(`/api/watchlists/items/${item.id}`);
      },
      t("watchlist.messages.deletedStock"),
      { keepSelection: true }
    );
  }

  async function toggleStockItem(item: WatchlistItemRead) {
    await runAction(
      async () => {
        await requestJson<WatchlistItemRead>(`/api/watchlists/items/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ enabled: !item.enabled }),
        });
      },
      item.enabled ? t("watchlist.messages.disabledStock") : t("watchlist.messages.enabledStock"),
      { keepSelection: true }
    );
  }

  function handleFolderSubmit(event: FormEvent<HTMLFormElement>) {
    const intent = submitterValue(event);
    event.preventDefault();
    if (intent === "create_child") void createChildFolder();
    else void createRootFolder();
  }

  function handleSelectedFolderSubmit(event: FormEvent<HTMLFormElement>) {
    const intent = submitterValue(event);
    event.preventDefault();
    if (intent === "delete") void deleteSelectedFolder();
    else void renameSelectedFolder();
  }

  function handleStockSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void createStockItem();
  }

  function renderPinnedIndexGroup() {
    const selected = PINNED_INDEX_ITEMS.some((item) =>
      item.kind === "index"
        ? item.stockId === selectedStockId
        : selectedFuturesSymbol !== null
    );

    return (
      <div>
        <div
          className={[
            "relative flex cursor-pointer items-center gap-1 py-1 pr-1 text-sm",
            selected ? "omi-sidebar-selected text-omi-text-strong" : "text-omi-text-muted hover:bg-omi-surface-muted",
          ].join(" ")}
          style={{ paddingLeft: "4px" }}
          onClick={() => setIndexGroupExpanded((previous) => !previous)}
        >
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setIndexGroupExpanded((previous) => !previous);
            }}
            className={[
              "h-6 w-4 text-xs",
              selected ? "text-omi-accent" : "text-omi-text-muted",
            ].join(" ")}
            aria-label={t("watchlist.toggleIndexFolder")}
          >
            {indexGroupExpanded ? "v" : ">"}
          </button>

          <div className="min-w-0 flex-1 text-left">
            <div className="truncate font-semibold">{PINNED_INDEX_GROUP_NAME}</div>
          </div>

          <span className={selected ? "pr-2 text-xs text-omi-accent" : "pr-2 text-xs text-omi-text-subtle"}>
            {PINNED_INDEX_ITEMS.length}
          </span>
        </div>

        {indexGroupExpanded ? (
          <div>
            {PINNED_INDEX_ITEMS.map((item) => {
              const itemSelected =
                item.kind === "index"
                  ? item.stockId === selectedStockId
                  : selectedFuturesSymbol !== null;
              const key = item.kind === "index" ? item.stockId : item.symbol;
              const quote =
                item.kind === "futures"
                  ? futuresQuotesBySymbol.get(item.symbol)
                  : null;
              const note =
                item.kind === "futures" && quote?.contract_month
                  ? t("watchlist.nearMonth", { month: quote.contract_month })
                  : item.note;

              return (
                <button
                  key={key}
                  type="button"
                  className={[
                    "group relative flex w-full cursor-pointer items-center gap-1 py-1.5 pr-2 text-left text-xs",
                    itemSelected
                      ? "omi-sidebar-selected text-omi-text-strong"
                      : "text-omi-text-muted hover:bg-omi-surface-muted",
                  ].join(" ")}
                  style={{ paddingLeft: "24px" }}
                  onMouseDown={(event) => {
                    if (event.button !== 0) return;
                    if (item.kind === "index") {
                      onSelectStock(item.stockId, item.stockName);
                    } else {
                      onSelectFutures?.(item.symbol);
                    }
                  }}
                  onClick={() => {
                    if (item.kind === "index") {
                      onSelectStock(item.stockId, item.stockName);
                    } else {
                      onSelectFutures?.(item.symbol);
                    }
                  }}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold">
                      {item.kind === "index"
                        ? `${item.stockId} ${item.stockName}`
                        : item.stockName}
                    </div>
                    <div className={itemSelected ? "truncate text-omi-text-muted" : "truncate text-omi-text-subtle"}>
                      {note}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    );
  }

  function renderGroupNode(node: WatchlistGroupNode, depth = 0) {
    const selected = node.id === selectedGroupId;
    const expanded = expandedIds.has(node.id);
    const children = node.children;
    const groupItems = itemsByGroupId.get(node.id) ?? [];
    const totalItemCount = countGroupItems(node);
    const hasContent = children.length > 0 || groupItems.length > 0;
    const groupDropBefore = dragOverKey === `group:${node.id}:before`;
    const groupDropInside = dragOverKey === `group:${node.id}:inside`;
    const groupDropAfter = dragOverKey === `group:${node.id}:after`;

    return (
      <div key={node.id}>
        <div
          className={[
            "relative flex cursor-pointer items-center gap-0.5 py-1 pr-1 text-sm",
            dragPayload?.type === "group" && dragPayload.groupId === node.id
              ? "opacity-50"
              : "",
            groupDropInside ? "ring-1 ring-inset ring-omi-accent" : "",
            selected ? "omi-sidebar-selected text-omi-text-strong" : "text-omi-text-muted hover:bg-omi-surface-muted",
          ].join(" ")}
          style={{ paddingLeft: `${6 + depth * 10}px` }}
          data-watchlist-group-id={node.id}
          onClick={() => selectGroup(node)}
        >
          {groupDropBefore ? (
            <div className="absolute left-0 right-0 top-0 h-0.5 bg-omi-accent" />
          ) : null}
          {groupDropAfter ? (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-omi-accent" />
          ) : null}
          <button
            type="button"
            aria-label={t("watchlist.moveGroup")}
            onPointerDown={(event) =>
              beginPointerDrag(event, { type: "group", groupId: node.id })
            }
            onClick={(event) => event.stopPropagation()}
            className={[
              "h-6 w-3 select-none text-[9px] font-bold leading-none",
              selected ? "text-omi-accent" : "text-omi-text-subtle hover:text-omi-accent",
            ].join(" ")}
          >
            ::
          </button>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              toggleExpanded(node.id);
            }}
            className={[
              "h-6 w-4 text-xs",
              selected ? "text-omi-accent" : "text-omi-text-muted",
              !hasContent ? "opacity-40" : "",
            ].join(" ")}
          >
            {hasContent ? (expanded ? "v" : ">") : "-"}
          </button>

          <div className="min-w-0 flex-1 text-left">
            <div className="truncate font-semibold">{node.group_name}</div>
          </div>

          <span className={selected ? "pr-2 text-xs text-omi-accent" : "pr-2 text-xs text-omi-text-subtle"}>
            {totalItemCount}
          </span>
        </div>

        {expanded ? (
          <div>
            {groupItems.map((item) => {
              const itemSelected = item.stock_id === selectedStockId;
              const stockDropBefore = dragOverKey === `stock:${item.id}:before`;

              return (
                <div
                  key={item.id}
                  className={[
                    "group relative flex cursor-pointer items-center gap-1 py-1.5 pr-2 text-xs",
                    dragPayload?.type === "stock" && dragPayload.itemId === item.id
                      ? "opacity-50"
                      : "",
                    itemSelected
                      ? "omi-sidebar-selected text-omi-text-strong"
                      : item.enabled
                        ? "text-omi-text-muted hover:bg-omi-surface-muted"
                        : "text-omi-text-subtle",
                  ].join(" ")}
                  style={{ paddingLeft: `${28 + depth * 10}px` }}
                  data-watchlist-stock-id={item.id}
                  onMouseDown={(event) => {
                    if (event.button !== 0 || isNestedInteractiveTarget(event.target)) {
                      return;
                    }
                    onSelectStock(item.stock_id, item.stock_name);
                  }}
                  onClick={(event) => {
                    if (isNestedInteractiveTarget(event.target)) return;
                    onSelectStock(item.stock_id, item.stock_name);
                  }}
                >
                  {stockDropBefore ? (
                    <div className="absolute left-0 right-0 top-0 h-0.5 bg-omi-accent" />
                  ) : null}
                  <button
                    type="button"
                    aria-label={t("watchlist.moveStock")}
                    onPointerDown={(event) =>
                      beginPointerDrag(event, {
                        type: "stock",
                        itemId: item.id,
                        groupId: item.group_id,
                        stockId: item.stock_id,
                      })
                    }
                    onClick={(event) => event.stopPropagation()}
                    className={[
                      "h-5 w-3 select-none text-[9px] font-bold leading-none",
                      itemSelected ? "text-omi-accent" : "text-omi-text-subtle hover:text-omi-accent",
                    ].join(" ")}
                  >
                    ::
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold">
                      {item.stock_id} {item.stock_name ?? ""}
                    </div>
                    {item.tags || item.note ? (
                      <div className={itemSelected ? "truncate text-omi-text-muted" : "truncate text-omi-text-subtle"}>
                        {item.tags || item.note}
                      </div>
                    ) : null}
                  </div>

                  <form
                    action="/omi-form/watchlists/items"
                    method="post"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void toggleStockItem(item);
                    }}
                  >
                    <input type="hidden" name="intent" value="toggle" />
                    <input type="hidden" name="item_id" value={item.id} />
                    <input type="hidden" name="group_id" value={item.group_id} />
                    <input type="hidden" name="enabled" value={String(!item.enabled)} />
                    <button
                      type="submit"
                      draggable={false}
                      onClick={(event) => event.stopPropagation()}
                      className={[
                        "hidden px-1.5 py-0.5 text-[10px] font-semibold group-hover:block",
                        itemSelected ? "bg-omi-surface text-omi-text" : "bg-omi-surface-strong text-omi-text-muted",
                      ].join(" ")}
                    >
                      {item.enabled ? "off" : "on"}
                    </button>
                  </form>

                  <form
                    action="/omi-form/watchlists/items"
                    method="post"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void deleteStockItem(item);
                    }}
                  >
                    <input type="hidden" name="intent" value="delete" />
                    <input type="hidden" name="item_id" value={item.id} />
                    <input type="hidden" name="group_id" value={item.group_id} />
                    <button
                      type="submit"
                      draggable={false}
                      onClick={(event) => event.stopPropagation()}
                      className="hidden bg-omi-danger-soft px-1.5 py-0.5 text-[10px] font-semibold text-omi-danger group-hover:block"
                    >
                      x
                    </button>
                  </form>
                </div>
              );
            })}

            {children.map((child) => renderGroupNode(child, depth + 1))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <aside className="flex max-h-[55vh] w-full shrink-0 flex-col border-b border-omi-border-subtle bg-omi-surface lg:h-full lg:max-h-none lg:w-[300px] lg:border-b-0 lg:border-r">
      <div className="border-b border-omi-border-subtle px-4 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.22em] text-omi-accent">
          Open Market Intelligence
        </div>
        <h1 className="mt-2 text-xl font-bold text-omi-text-strong">{t("app.dashboardTitle")}</h1>
        <div className="mt-3 grid grid-cols-5 border border-omi-border-subtle bg-omi-surface-subtle p-1">
          {sidebarMarketOptions.map((option) => (
            <a
              key={option.value}
              href={option.enabled ? `/?market=${option.value}` : undefined}
              aria-disabled={!option.enabled}
              onClick={(event) => {
                if (!option.enabled) {
                  event.preventDefault();
                  return;
                }

                event.preventDefault();
                onMarketChange(option.value);
              }}
              className={[
                "flex h-8 items-center justify-center text-xs font-semibold transition",
                selectedMarket === option.value
                  ? "omi-sidebar-market-tab-active"
                  : option.enabled
                    ? "text-omi-text-muted hover:bg-omi-surface"
                    : "cursor-not-allowed text-omi-text-subtle",
              ].join(" ")}
            >
              {marketLabel(t, option.value)}
            </a>
          ))}
        </div>
      </div>

      {selectedMarket === "tw" ? (
        <>
      <div className="flex items-center justify-between border-b border-omi-border-subtle px-4 py-3">
        <div>
          <div className="text-xs font-semibold text-omi-text-muted">{t("watchlist.header")}</div>
          <div className="text-sm font-bold text-omi-text-strong">
            {selectedGroup?.group_name ?? t("watchlist.noGroupSelected")}
          </div>
        </div>
        <button
          type="button"
          className={buttonClass("ghost")}
          onClick={() => void reloadSelectedGroupList()}
          disabled={loading || reloadingExplorerData}
        >
          {reloadingExplorerData ? t("common.reloading") : t("common.reloadList")}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {dragPayload?.type === "group" ? (
          <div
            className={[
              "mx-2 mb-2 border border-dashed px-3 py-2 text-center text-xs font-semibold",
              dragOverKey === "root"
                ? "border-omi-accent bg-omi-danger-soft text-omi-danger"
                : "border-omi-border text-omi-text-muted",
            ].join(" ")}
            data-watchlist-root-drop="true"
          >
            {t("watchlist.moveToRoot")}
          </div>
        ) : null}
        {renderPinnedIndexGroup()}
        <PortfolioHoldingsPanel
          market="tw"
          selectedSymbol={selectedStockId}
          defaultCurrency="TWD"
          symbolPlaceholder={t("watchlist.stockInputPlaceholder")}
          normalizeSymbol={(value) => value.trim().toUpperCase()}
          onSelectSymbol={onSelectStock}
        />
        {tree.length > 0 ? (
          tree.map((node) => renderGroupNode(node))
        ) : (
          <div className="px-4 py-6 text-sm text-omi-text-muted">{t("watchlist.noGroupCreated")}</div>
        )}
      </div>

      {pointerDrag?.active ? (
        <div
          className="pointer-events-none fixed z-50 max-w-48 border border-omi-border bg-omi-surface px-2 py-1 text-xs font-semibold text-omi-text shadow-sm"
          style={{
            left: pointerDrag.currentX + 10,
            top: pointerDrag.currentY + 10,
          }}
        >
          {getDragLabel(pointerDrag.payload)}
        </div>
      ) : null}

      {message ? (
        <div
          className={[
            "mx-4 mb-3 border px-3 py-2 text-xs",
            message.type === "success"
              ? "border-omi-market-down-border bg-omi-market-down-soft text-omi-market-down"
              : "border-omi-danger-border bg-omi-danger-soft text-omi-danger",
          ].join(" ")}
        >
          {message.text}
        </div>
      ) : null}

      <div className="border-b border-omi-border-subtle px-4 py-4">
        <JobStatusCenter placement="inline" market="tw" />
      </div>

      <div className="space-y-4 p-4">
        <form
          action="/omi-form/watchlists/groups"
          method="post"
          onSubmit={handleFolderSubmit}
        >
          <div className="mb-2 text-xs font-bold text-omi-text-muted">{t("watchlist.groupManagement")}</div>
          <input
            className={inputClass()}
            name="group_name"
            placeholder={t("watchlist.addGroupPlaceholder")}
            value={folderName}
            onChange={(event) => setFolderName(event.target.value)}
          />
          <input type="hidden" name="parent_id" value={selectedGroupId ?? ""} />
          <div className="mt-2 flex gap-2">
            <button
              type="submit"
              name="intent"
              value="create_root"
              className={buttonClass("ghost")}
              disabled={loading}
            >
              {t("common.addRoot")}
            </button>
            <button
              type="submit"
              name="intent"
              value="create_child"
              className={buttonClass("primary")}
              disabled={loading || selectedGroupId === null}
            >
              {t("common.addChild")}
            </button>
          </div>
        </form>

        <form
          action="/omi-form/watchlists/groups"
          method="post"
          onSubmit={handleSelectedFolderSubmit}
          className="space-y-2"
        >
          <input type="hidden" name="group_id" value={selectedGroupId ?? ""} />
          <input
            className={inputClass()}
            name="group_name"
            placeholder={t("watchlist.renameGroupPlaceholder")}
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
          />
          <div className="flex gap-2">
            <button
              type="submit"
              name="intent"
              value="rename"
              className={buttonClass("primary")}
              disabled={loading || selectedGroupId === null}
            >
              {t("common.rename")}
            </button>
            <button
              type="submit"
              name="intent"
              value="delete"
              className={buttonClass("danger")}
              disabled={loading || selectedGroupId === null}
            >
              {t("common.delete")}
            </button>
          </div>
        </form>

        <div className="space-y-2">
          <form
            id="tw-watchlist-stock-form"
            action="/omi-form/watchlists/items"
            method="post"
            onSubmit={handleStockSubmit}
            className="space-y-2"
          >
            <div className="text-xs font-bold text-omi-text-muted">{t("watchlist.addStock")}</div>
            <input type="hidden" name="intent" value="create" />
            <input type="hidden" name="group_id" value={selectedGroupId ?? ""} />
            <input
              className={inputClass()}
              name="stock_id"
              placeholder={t("watchlist.stockInputPlaceholder")}
              value={stockInput}
              onChange={(event) => setStockInput(event.target.value)}
            />
            {stockSuggestions.length > 0 ? (
              <div className="max-h-28 overflow-y-auto border border-omi-border-subtle bg-omi-surface">
                {stockSuggestions.map((stock) => (
                  <button
                    key={stock.stock_id}
                    type="button"
                    className="block w-full px-3 py-1.5 text-left text-xs text-omi-text-muted hover:bg-omi-surface-muted"
                    onClick={() => {
                      setStockInput(stock.stock_id);
                      setStockSuggestions([]);
                    }}
                  >
                    {stock.stock_id} {stock.stock_name ?? ""} · {stock.market}
                  </button>
                ))}
              </div>
            ) : null}
            <input
              className={inputClass()}
              name="note"
              placeholder={t("watchlist.notePlaceholder")}
              value={stockNote}
              onChange={(event) => setStockNote(event.target.value)}
            />
            <input
              className={inputClass()}
              name="tags"
              placeholder={t("watchlist.tagsPlaceholder")}
              value={stockTags}
              onChange={(event) => setStockTags(event.target.value)}
            />
          </form>
          <div className="flex items-center justify-between gap-2">
            <button
              type="submit"
              form="tw-watchlist-stock-form"
              className={buttonClass("primary")}
              disabled={loading || selectedGroupId === null}
            >
              {t("common.addStock")}
            </button>
            <SettingsDock placement="inline" />
          </div>
        </div>
      </div>
        </>
      ) : selectedMarket === "crypto" ? (
        <SidebarCryptoControls
          selectedBase={selectedCryptoBase}
          selectedInstrumentKey={selectedCryptoInstrumentKey}
          selectedResourceInstrumentKey={selectedResourceInstrumentKey}
          onSelectInstrument={onSelectCryptoInstrument}
          onSelectResourceInstrument={onSelectResourceInstrument}
        />
      ) : (
        <SidebarMarketSummary selectedMarket={selectedMarket} />
      )}
    </aside>
  );
}

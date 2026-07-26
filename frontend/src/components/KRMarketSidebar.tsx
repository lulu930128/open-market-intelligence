"use client";

import JobStatusCenter from "@/components/JobStatusCenter";
import PortfolioHoldingsPanel from "@/components/PortfolioHoldingsPanel";
import SettingsDock from "@/components/SettingsDock";
import { marketLabel, useT } from "@/i18n";
import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type { MarketRegion } from "@/components/market-dashboard/selection/dashboardRoutes";
import {
  KR_MARKET_INDEX_GROUP_NAME,
  KR_MARKET_INDEX_ITEMS,
} from "@/lib/krMarketIndices";
import type {
  KRStockMasterRead,
  KRWatchlistGroupNode,
  KRWatchlistGroupRead,
  KRWatchlistItemRead,
} from "@/types/market";
import { FormEvent, type MouseEvent as ReactMouseEvent, useMemo, useState } from "react";

type Message = { type: "success" | "warning" | "error"; text: string } | null;

type Props = {
  initialTree: KRWatchlistGroupNode[];
  initialItems: KRWatchlistItemRead[];
  selectedMarket: MarketRegion;
  selectedGroupId: number | null;
  selectedSymbol: string | null;
  selectedStock: KRStockMasterRead | null;
  externalStatusMessage?: Message;
  onMarketChange: (market: MarketRegion) => void;
  onSelectGroup?: (group: KRWatchlistGroupNode | null) => void;
  onSelectSymbol: (symbol: string, securityName: string | null) => void;
  onExplorerDataChanged?: (
    tree: KRWatchlistGroupNode[],
    items: KRWatchlistItemRead[]
  ) => void;
};

const marketOptions: Array<{
  value: MarketRegion;
  enabled: boolean;
}> = [
  { value: "tw", enabled: true },
  { value: "us", enabled: true },
  { value: "jp", enabled: true },
  { value: "kr", enabled: true },
  { value: "crypto", enabled: true },
];

function flattenGroups(nodes: KRWatchlistGroupNode[]): KRWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
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

function submitterValue(event: FormEvent<HTMLFormElement>) {
  const nativeEvent = event.nativeEvent as SubmitEvent;
  const submitter = nativeEvent.submitter as HTMLButtonElement | null;
  return submitter?.value ?? "";
}

function selectOnPrimaryMouseDown(
  event: ReactMouseEvent<HTMLElement>,
  select: () => void
) {
  if (event.button !== 0) return;
  select();
}

function normalizeSymbolInput(value: string) {
  let cleaned = value.trim().toUpperCase();
  if (!cleaned) return "";

  if (cleaned.includes(":")) {
    cleaned = cleaned.split(":").pop()?.trim() ?? cleaned;
  }

  if (cleaned.includes("/")) {
    cleaned = cleaned.split("/")[0].trim();
  }

  return cleaned.match(/^[A-Z0-9][A-Z0-9.\-]*/)?.[0] ?? "";
}

export default function KRMarketSidebar({
  initialTree,
  initialItems,
  selectedMarket,
  selectedGroupId,
  selectedSymbol,
  selectedStock,
  externalStatusMessage,
  onMarketChange,
  onSelectGroup,
  onSelectSymbol,
  onExplorerDataChanged,
}: Props) {
  const t = useT();
  const initialGroup =
    flattenGroups(initialTree).find((group) => group.id === selectedGroupId) ??
    flattenGroups(initialTree)[0] ??
    null;
  const [tree, setTree] = useState<KRWatchlistGroupNode[]>(initialTree);
  const [items, setItems] = useState<KRWatchlistItemRead[]>(initialItems);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [currentGroupId, setCurrentGroupId] = useState<number | null>(
    initialGroup?.id ?? null
  );
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [folderName, setFolderName] = useState("");
  const [renameValue, setRenameValue] = useState(initialGroup?.group_name ?? "");
  const [symbolInput, setSymbolInput] = useState("");
  const [stockNote, setStockNote] = useState("");
  const [stockTags, setStockTags] = useState("");
  const [stockSuggestions, setStockSuggestions] = useState<KRStockMasterRead[]>([]);
  const [indexGroupExpanded, setIndexGroupExpanded] = useState(false);

  const allGroups = useMemo(() => flattenGroups(tree), [tree]);
  const selectedGroup = useMemo(
    () => allGroups.find((group) => group.id === currentGroupId) ?? null,
    [allGroups, currentGroupId]
  );
  const itemsByGroupId = useMemo(() => {
    const map = new Map<number, KRWatchlistItemRead[]>();

    items.forEach((item) => {
      const list = map.get(item.group_id) ?? [];
      list.push(item);
      map.set(item.group_id, list);
    });

    return map;
  }, [items]);
  const selectedLabel = selectedStock
    ? `${selectedStock.symbol} ${selectedStock.security_name ?? selectedStock.security_name_kr ?? ""}`.trim()
    : selectedSymbol ?? t("krMarket.sidebar.noSelection");
  const statusMessage = externalStatusMessage ?? message;

  function countGroupItems(node: KRWatchlistGroupNode): number {
    const directCount = itemsByGroupId.get(node.id)?.length ?? 0;
    return directCount + node.children.reduce((total, child) => total + countGroupItems(child), 0);
  }

  function selectGroup(group: KRWatchlistGroupNode) {
    setCurrentGroupId(group.id);
    setRenameValue(group.group_name);
    onSelectGroup?.(group);
    setExpandedIds((previous) => new Set(previous).add(group.id));
  }

  async function reloadData(options?: { keepSelection?: boolean }) {
    const [treeData, itemData] = await Promise.all([
      fetchJson<KRWatchlistGroupNode[]>("/api/kr-market/watchlists/tree"),
      fetchJson<KRWatchlistItemRead[]>("/api/kr-market/watchlists/items", {
        limit: 5000,
        offset: 0,
      }),
    ]);
    const flattened = flattenGroups(treeData);
    const nextSelected =
      options?.keepSelection && currentGroupId !== null
        ? flattened.find((group) => group.id === currentGroupId) ?? null
        : flattened[0] ?? null;

    setTree(treeData);
    setItems(itemData);
    onExplorerDataChanged?.(treeData, itemData);
    setCurrentGroupId(nextSelected?.id ?? null);
    setRenameValue(nextSelected?.group_name ?? "");

    return nextSelected;
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
      await reloadData({ keepSelection: options?.keepSelection ?? true });
      setMessage({ type: "success", text: successText });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("krMarket.watchlist.messages.actionError"),
      });
    } finally {
      setLoading(false);
    }
  }

  async function reloadSidebarData() {
    setLoading(true);
    setMessage(null);

    try {
      await reloadData({ keepSelection: true });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("krMarket.watchlist.messages.reloadError"),
      });
    } finally {
      setLoading(false);
    }
  }

  async function createRootFolder() {
    const groupName = folderName.trim();
    if (!groupName) return;

    await runAction(
      async () => {
        await requestJson<KRWatchlistGroupRead>("/api/kr-market/watchlists/groups", {
          method: "POST",
          body: JSON.stringify({
            parent_id: null,
            group_name: groupName,
            description: null,
            sort_order: 100,
            is_active: true,
          }),
        });
        setFolderName("");
      },
      t("krMarket.watchlist.messages.createdRoot"),
      { keepSelection: false }
    );
  }

  async function createChildFolder() {
    const groupName = folderName.trim();
    if (!groupName || currentGroupId === null) return;

    await runAction(
      async () => {
        await requestJson<KRWatchlistGroupRead>("/api/kr-market/watchlists/groups", {
          method: "POST",
          body: JSON.stringify({
            parent_id: currentGroupId,
            group_name: groupName,
            description: null,
            sort_order: 100,
            is_active: true,
          }),
        });
        setFolderName("");
      },
      t("krMarket.watchlist.messages.createdChild")
    );
  }

  async function renameSelectedFolder() {
    const groupName = renameValue.trim();
    if (!groupName || currentGroupId === null) return;

    await runAction(
      async () => {
        await requestJson<KRWatchlistGroupRead>(
          `/api/kr-market/watchlists/groups/${currentGroupId}`,
          {
            method: "PATCH",
            body: JSON.stringify({ group_name: groupName }),
          }
        );
      },
      t("krMarket.watchlist.messages.renamedGroup")
    );
  }

  async function deleteSelectedFolder() {
    if (currentGroupId === null) return;
    if (!window.confirm(t("krMarket.watchlist.confirmDeleteGroup"))) return;

    await runAction(
      async () => {
        await requestJson(`/api/kr-market/watchlists/groups/${currentGroupId}`, {
          method: "DELETE",
        }, { recursive: true });
      },
      t("krMarket.watchlist.messages.deletedGroup"),
      { keepSelection: false }
    );
  }

  async function findStockSuggestions() {
    const keyword = symbolInput.trim();
    if (keyword.length < 1) {
      setStockSuggestions([]);
      return;
    }

    const normalizedSymbol = normalizeSymbolInput(keyword);
    const suggestions: KRStockMasterRead[] = [];

    if (normalizedSymbol) {
      try {
        const exactMatch = await fetchJson<KRStockMasterRead>(
          `/api/kr-market/stocks/${encodeURIComponent(normalizedSymbol)}`
        );
        suggestions.push(exactMatch);
      } catch {
        // Search below still covers names and un-normalized codes.
      }
    }

    try {
      const rows = await fetchJson<KRStockMasterRead[]>("/api/kr-market/stocks/search", {
        keyword,
        limit: 8,
      });

      for (const row of rows) {
        if (!suggestions.some((candidate) => candidate.symbol === row.symbol)) {
          suggestions.push(row);
        }
      }

      setStockSuggestions(suggestions);
    } catch {
      setStockSuggestions(suggestions);
    }
  }

  async function createStockItem() {
    const symbol = normalizeSymbolInput(symbolInput || selectedStock?.symbol || "");
    if (!symbol || currentGroupId === null) return;

    await runAction(
      async () => {
        const item = await requestJson<KRWatchlistItemRead>(
          "/api/kr-market/watchlists/items",
          {
            method: "POST",
            body: JSON.stringify({
              group_id: currentGroupId,
              symbol,
              note: stockNote.trim() || null,
              priority: 100,
              tags: stockTags.trim() || null,
              enabled: true,
            }),
          }
        );

        setSymbolInput("");
        setStockNote("");
        setStockTags("");
        setStockSuggestions([]);
        onSelectSymbol(item.symbol, item.security_name ?? item.security_name_kr);
      },
      t("krMarket.watchlist.messages.addedStock")
    );
  }

  async function deleteStockItem(item: KRWatchlistItemRead) {
    if (!window.confirm(t("krMarket.watchlist.confirmDeleteStock", { symbol: item.symbol }))) {
      return;
    }

    await runAction(
      async () => {
        await deleteRequest(`/api/kr-market/watchlists/items/${item.id}`);
      },
      t("krMarket.watchlist.messages.deletedStock")
    );
  }

  async function toggleStockItem(item: KRWatchlistItemRead) {
    await runAction(
      async () => {
        await requestJson<KRWatchlistItemRead>(
          `/api/kr-market/watchlists/items/${item.id}`,
          {
            method: "PATCH",
            body: JSON.stringify({ enabled: !item.enabled }),
          }
        );
      },
      item.enabled
        ? t("krMarket.watchlist.messages.disabledStock")
        : t("krMarket.watchlist.messages.enabledStock")
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
    const selected = KR_MARKET_INDEX_ITEMS.some((item) => item.symbol === selectedSymbol);

    return (
      <div>
        <div
          className={[
            "relative flex cursor-pointer items-center gap-1 py-1 pr-1 text-sm",
            selected
              ? "omi-sidebar-selected text-omi-text-strong"
              : "text-omi-text-muted hover:bg-omi-surface-muted",
          ].join(" ")}
          style={{ paddingLeft: "4px" }}
          onClick={() => setIndexGroupExpanded((previous) => !previous)}
        >
          <button
            type="button"
            className={[
              "h-6 w-4 text-xs",
              selected ? "text-omi-accent" : "text-omi-text-muted",
            ].join(" ")}
            onClick={(event) => {
              event.stopPropagation();
              setIndexGroupExpanded((previous) => !previous);
            }}
            aria-label={t("krMarket.watchlist.toggleIndexFolder")}
          >
            {indexGroupExpanded ? "v" : ">"}
          </button>
          <div className="min-w-0 flex-1 truncate font-semibold">
            {KR_MARKET_INDEX_GROUP_NAME}
          </div>
          <span className={selected ? "pr-2 text-xs text-omi-accent" : "pr-2 text-xs text-omi-text-subtle"}>
            {KR_MARKET_INDEX_ITEMS.length}
          </span>
        </div>

        {indexGroupExpanded ? (
          <div>
            {KR_MARKET_INDEX_ITEMS.map((item) => {
              const itemSelected = item.symbol === selectedSymbol;

              return (
                <button
                  key={item.symbol}
                  type="button"
                  className={[
                    "group relative flex w-full cursor-pointer items-center gap-1 py-1.5 pr-2 text-left text-xs",
                    itemSelected
                      ? "omi-sidebar-selected text-omi-text-strong"
                      : "text-omi-text-muted hover:bg-omi-surface-muted",
                  ].join(" ")}
                  style={{ paddingLeft: "24px" }}
                  onMouseDown={(event) =>
                    selectOnPrimaryMouseDown(event, () =>
                      onSelectSymbol(item.symbol, item.name)
                    )
                  }
                  onClick={() => onSelectSymbol(item.symbol, item.name)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold">
                      {item.displaySymbol} {item.name}
                    </div>
                    <div className={itemSelected ? "truncate text-omi-text-muted" : "truncate text-omi-text-subtle"}>
                      {item.exchange} / index / {item.note}
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

  function renderGroupNode(node: KRWatchlistGroupNode, depth = 0) {
    const selected = node.id === currentGroupId;
    const expanded = expandedIds.has(node.id);
    const childItems = itemsByGroupId.get(node.id) ?? [];
    const hasChildren = node.children.length > 0 || childItems.length > 0;

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
          onClick={() => selectGroup(node)}
        >
          <button
            type="button"
            className={selected ? "h-6 w-4 text-xs text-omi-accent" : "h-6 w-4 text-xs text-omi-text-muted"}
            onClick={(event) => {
              event.stopPropagation();
              setExpandedIds((previous) => {
                const next = new Set(previous);
                if (next.has(node.id)) next.delete(node.id);
                else next.add(node.id);
                return next;
              });
            }}
          >
            {hasChildren ? (expanded ? "v" : ">") : ""}
          </button>
          <div className="min-w-0 flex-1 truncate font-semibold">{node.group_name}</div>
          <span className={selected ? "pr-2 text-xs text-omi-accent" : "pr-2 text-xs text-omi-text-subtle"}>
            {countGroupItems(node)}
          </span>
        </div>

        {expanded ? (
          <div>
            {childItems.map((item) => {
              const itemSelected = item.symbol === selectedSymbol;
              const itemName = item.security_name ?? item.security_name_kr ?? "";

              return (
                <div
                  key={item.id}
                  className={[
                    "group relative flex items-center gap-1 py-1.5 pr-2 text-xs",
                    itemSelected
                      ? "omi-sidebar-selected text-omi-text-strong"
                      : "text-omi-text-muted hover:bg-omi-surface-muted",
                  ].join(" ")}
                  style={{ paddingLeft: `${24 + depth * 16}px` }}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => onSelectSymbol(item.symbol, itemName || null)}
                  >
                    <div className="truncate font-semibold">
                      {item.symbol} {itemName}
                    </div>
                    <div className={itemSelected ? "truncate text-omi-text-muted" : "truncate text-omi-text-subtle"}>
                      {[item.market_segment, item.sector].filter(Boolean).join(" / ")}
                    </div>
                  </button>
                  <button
                    type="button"
                    className={[
                      "hidden px-1.5 py-0.5 text-[10px] font-semibold group-hover:block",
                      itemSelected
                        ? "bg-omi-surface text-omi-text"
                        : "bg-omi-surface-strong text-omi-text-muted",
                    ].join(" ")}
                    onClick={() => void toggleStockItem(item)}
                  >
                    {item.enabled ? t("common.disabled") : t("common.enabled")}
                  </button>
                  <button
                    type="button"
                    className="hidden bg-omi-danger-soft px-1.5 py-0.5 text-[10px] font-semibold text-omi-danger group-hover:block"
                    onClick={() => void deleteStockItem(item)}
                  >
                    {t("common.deleteShort")}
                  </button>
                </div>
              );
            })}

            {node.children.map((child) => renderGroupNode(child, depth + 1))}
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
        <h1 className="mt-2 text-xl font-bold text-omi-text-strong">
          {t("app.dashboardTitle")}
        </h1>
        <div className="mt-3 grid grid-cols-5 border border-omi-border-subtle bg-omi-surface-subtle p-1">
          {marketOptions.map((option) => (
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

      <div className="flex items-center justify-between border-b border-omi-border-subtle px-4 py-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-omi-text-muted">
            {t("krMarket.sidebar.header")}
          </div>
          <div className="truncate text-sm font-bold text-omi-text-strong">
            {selectedGroup?.group_name ?? t("krMarket.watchlist.noGroupCreated")}
          </div>
          <div className="mt-1 truncate text-xs text-omi-text-muted">{selectedLabel}</div>
        </div>
        <button
          type="button"
          className={buttonClass("ghost")}
          onClick={() => void reloadSidebarData()}
          disabled={loading}
        >
          {t("common.reload")}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {renderPinnedIndexGroup()}
        <PortfolioHoldingsPanel
          market="kr"
          selectedSymbol={selectedSymbol}
          defaultCurrency="KRW"
          symbolPlaceholder={t("krMarket.watchlist.symbolPlaceholder")}
          normalizeSymbol={normalizeSymbolInput}
          onSelectSymbol={onSelectSymbol}
        />
        {tree.length > 0 ? (
          tree.map((node) => renderGroupNode(node))
        ) : (
          <div className="px-4 py-6 text-sm text-omi-text-muted">
            {t("krMarket.watchlist.noGroupCreated")}
          </div>
        )}
      </div>

      <div className="space-y-2 border-b border-omi-border-subtle px-4 py-4">
        <JobStatusCenter placement="inline" market="kr" />
        {statusMessage ? (
          <div
            className={[
              "border px-3 py-2 text-xs",
              statusMessage.type === "success"
                ? "border-omi-market-down-border bg-omi-market-down-soft text-omi-market-down"
                : statusMessage.type === "warning"
                  ? "border-omi-warning-border bg-omi-warning-soft text-omi-warning"
                  : "border-omi-danger-border bg-omi-danger-soft text-omi-danger",
            ].join(" ")}
          >
            {statusMessage.text}
          </div>
        ) : null}
      </div>

      <div className="space-y-4 p-4">
        <form action="/" method="post" onSubmit={handleFolderSubmit}>
          <div className="mb-2 text-xs font-bold text-omi-text-muted">
            {t("krMarket.watchlist.groupManagement")}
          </div>
          <input
            className={inputClass()}
            name="group_name"
            placeholder={t("krMarket.watchlist.addGroupPlaceholder")}
            value={folderName}
            onChange={(event) => setFolderName(event.target.value)}
          />
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
              disabled={loading || currentGroupId === null}
            >
              {t("common.addChild")}
            </button>
          </div>
        </form>

        <form action="/" method="post" onSubmit={handleSelectedFolderSubmit} className="space-y-2">
          <input
            className={inputClass()}
            name="group_name"
            placeholder={t("krMarket.watchlist.renameGroupPlaceholder")}
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
          />
          <div className="flex gap-2">
            <button
              type="submit"
              name="intent"
              value="rename"
              className={buttonClass("primary")}
              disabled={loading || currentGroupId === null}
            >
              {t("common.rename")}
            </button>
            <button
              type="submit"
              name="intent"
              value="delete"
              className={buttonClass("danger")}
              disabled={loading || currentGroupId === null}
            >
              {t("common.delete")}
            </button>
          </div>
        </form>

        <div className="space-y-2">
          <form
            id="kr-watchlist-stock-form"
            action="/"
            method="post"
            onSubmit={handleStockSubmit}
            className="space-y-2"
          >
            <div className="text-xs font-bold text-omi-text-muted">
              {t("krMarket.watchlist.addStock")}
            </div>
            <div className="flex gap-2">
              <input
                className={inputClass()}
                name="symbol"
                placeholder={t("krMarket.watchlist.symbolPlaceholder")}
                value={symbolInput}
                onChange={(event) => setSymbolInput(event.target.value)}
              />
              <button
                type="button"
                className={buttonClass("ghost")}
                onClick={() => void findStockSuggestions()}
                disabled={loading}
              >
                {t("common.find")}
              </button>
            </div>
            {stockSuggestions.length > 0 ? (
              <div className="max-h-28 overflow-y-auto border border-omi-border-subtle bg-omi-surface">
                {stockSuggestions.map((stock) => (
                  <button
                    key={stock.symbol}
                    type="button"
                    className="block w-full px-3 py-1.5 text-left text-xs text-omi-text-muted hover:bg-omi-surface-muted"
                    onClick={() => {
                      setSymbolInput(stock.symbol);
                      setStockSuggestions([]);
                    }}
                  >
                    {stock.symbol} {stock.security_name ?? stock.security_name_kr ?? ""} / {stock.market_segment ?? "-"}
                  </button>
                ))}
              </div>
            ) : null}
            <input
              className={inputClass()}
              name="note"
              placeholder={t("krMarket.watchlist.notePlaceholder")}
              value={stockNote}
              onChange={(event) => setStockNote(event.target.value)}
            />
            <input
              className={inputClass()}
              name="tags"
              placeholder={t("krMarket.watchlist.tagsPlaceholder")}
              value={stockTags}
              onChange={(event) => setStockTags(event.target.value)}
            />
          </form>
          <div className="flex items-center justify-between gap-2">
            <button
              type="submit"
              form="kr-watchlist-stock-form"
              className={buttonClass("primary")}
              disabled={loading || currentGroupId === null}
            >
              {t("common.addStock")}
            </button>
            <SettingsDock placement="inline" />
          </div>
        </div>
      </div>
    </aside>
  );
}

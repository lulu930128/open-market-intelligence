"use client";

import JobStatusCenter from "@/components/JobStatusCenter";
import SettingsDock from "@/components/SettingsDock";
import type { MarketRegion } from "@/components/SidebarWatchlistExplorer";
import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import {
  US_MARKET_INDEX_GROUP_NAME,
  US_MARKET_INDEX_ITEMS,
} from "@/lib/usMarketIndices";
import type {
  USStockMasterRead,
  USWatchlistGroupNode,
  USWatchlistGroupRead,
  USWatchlistItemRead,
} from "@/types/market";
import { FormEvent, type MouseEvent as ReactMouseEvent, useMemo, useState } from "react";

type Message = { type: "success" | "error"; text: string } | null;

type Props = {
  initialTree: USWatchlistGroupNode[];
  initialItems: USWatchlistItemRead[];
  selectedMarket: MarketRegion;
  selectedSymbol: string | null;
  onMarketChange: (market: MarketRegion) => void;
  onSelectGroup?: (group: USWatchlistGroupNode | null) => void;
  onSelectSymbol: (symbol: string, securityName: string | null) => void;
  onExplorerDataChanged?: (
    tree: USWatchlistGroupNode[],
    items: USWatchlistItemRead[]
  ) => void;
  onChanged?: () => void;
};

const marketOptions: Array<{
  label: string;
  value: MarketRegion;
  enabled: boolean;
}> = [
  { label: "台股", value: "tw", enabled: true },
  { label: "美股", value: "us", enabled: true },
  { label: "日股", value: "jp", enabled: false },
  { label: "韓股", value: "kr", enabled: false },
  { label: "港股", value: "hk", enabled: false },
];

function flattenGroups(nodes: USWatchlistGroupNode[]): USWatchlistGroupNode[] {
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

function normalizeTickerInput(value: string) {
  let cleaned = value.trim().toUpperCase();
  if (!cleaned) return "";

  if (cleaned.includes(":")) {
    cleaned = cleaned.split(":").pop()?.trim() ?? cleaned;
  }

  if (cleaned.includes("/")) {
    cleaned = cleaned.split("/")[0].trim();
  }

  return cleaned.match(/^[A-Z0-9][A-Z0-9.$-]*/)?.[0] ?? "";
}

export default function USWatchlistSidebar({
  initialTree,
  initialItems,
  selectedMarket,
  selectedSymbol,
  onMarketChange,
  onSelectGroup,
  onSelectSymbol,
  onExplorerDataChanged,
  onChanged,
}: Props) {
  const initialGroup = flattenGroups(initialTree)[0] ?? null;
  const [tree, setTree] = useState<USWatchlistGroupNode[]>(initialTree);
  const [items, setItems] = useState<USWatchlistItemRead[]>(initialItems);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(
    initialGroup?.id ?? null
  );
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [folderName, setFolderName] = useState("");
  const [renameValue, setRenameValue] = useState(initialGroup?.group_name ?? "");
  const [symbolInput, setSymbolInput] = useState("");
  const [stockNote, setStockNote] = useState("");
  const [stockTags, setStockTags] = useState("");
  const [stockSuggestions, setStockSuggestions] = useState<USStockMasterRead[]>([]);
  const [indexGroupExpanded, setIndexGroupExpanded] = useState(true);

  const allGroups = useMemo(() => flattenGroups(tree), [tree]);
  const selectedGroup = useMemo(() => {
    return allGroups.find((group) => group.id === selectedGroupId) ?? null;
  }, [allGroups, selectedGroupId]);
  const itemsByGroupId = useMemo(() => {
    const map = new Map<number, USWatchlistItemRead[]>();

    items.forEach((item) => {
      const list = map.get(item.group_id) ?? [];
      list.push(item);
      map.set(item.group_id, list);
    });

    return map;
  }, [items]);

  function countGroupItems(node: USWatchlistGroupNode): number {
    const directCount = itemsByGroupId.get(node.id)?.length ?? 0;
    return (
      directCount +
      node.children.reduce((total, child) => total + countGroupItems(child), 0)
    );
  }

  function selectGroup(group: USWatchlistGroupNode) {
    setSelectedGroupId(group.id);
    setRenameValue(group.group_name);
    onSelectGroup?.(group);
    setExpandedIds((previous) => {
      const next = new Set(previous);
      next.add(group.id);
      return next;
    });
  }

  async function reloadData(options?: { keepSelection?: boolean }) {
    const [treeData, itemData] = await Promise.all([
      fetchJson<USWatchlistGroupNode[]>("/api/us-market/watchlists/tree"),
      fetchJson<USWatchlistItemRead[]>("/api/us-market/watchlists/items", {
        limit: 5000,
        offset: 0,
      }),
    ]);
    const flattened = flattenGroups(treeData);
    const nextSelected =
      options?.keepSelection && selectedGroupId !== null
        ? flattened.find((group) => group.id === selectedGroupId) ?? null
        : flattened[0] ?? null;

    setTree(treeData);
    setItems(itemData);
    onExplorerDataChanged?.(treeData, itemData);
    setSelectedGroupId(nextSelected?.id ?? null);
    setRenameValue(nextSelected?.group_name ?? "");
    onSelectGroup?.(nextSelected);

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
      onChanged?.();
      setMessage({ type: "success", text: successText });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "操作失敗",
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
      onChanged?.();
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "??憭望?",
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
        await requestJson<USWatchlistGroupRead>("/api/us-market/watchlists/groups", {
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
      "已新增美股 Root 分組",
      { keepSelection: false }
    );
  }

  async function createChildFolder() {
    const groupName = folderName.trim();
    if (!groupName || selectedGroupId === null) return;

    await runAction(
      async () => {
        await requestJson<USWatchlistGroupRead>("/api/us-market/watchlists/groups", {
          method: "POST",
          body: JSON.stringify({
            parent_id: selectedGroupId,
            group_name: groupName,
            description: null,
            sort_order: 100,
            is_active: true,
          }),
        });
        setFolderName("");
      },
      "已新增美股 Child 分組"
    );
  }

  async function renameSelectedFolder() {
    const groupName = renameValue.trim();
    if (!groupName || selectedGroupId === null) return;

    await runAction(
      async () => {
        await requestJson<USWatchlistGroupRead>(
          `/api/us-market/watchlists/groups/${selectedGroupId}`,
          {
            method: "PATCH",
            body: JSON.stringify({ group_name: groupName }),
          }
        );
      },
      "已重新命名美股分組"
    );
  }

  async function deleteSelectedFolder() {
    if (selectedGroupId === null) return;

    const confirmed = window.confirm("刪除此美股分組與底下所有子分組、自選股？");
    if (!confirmed) return;

    await runAction(
      async () => {
        await requestJson(`/api/us-market/watchlists/groups/${selectedGroupId}`, {
          method: "DELETE",
        }, {
          recursive: true,
        });
      },
      "已刪除美股分組",
      { keepSelection: false }
    );
  }

  async function findStockSuggestions() {
    const keyword = symbolInput.trim();
    if (keyword.length < 1) {
      setStockSuggestions([]);
      return;
    }

    const normalizedSymbol = normalizeTickerInput(keyword);
    const suggestions: USStockMasterRead[] = [];

    if (normalizedSymbol) {
      try {
        const exactMatch = await fetchJson<USStockMasterRead>(
          `/api/us-market/stocks/${encodeURIComponent(normalizedSymbol)}`
        );
        suggestions.push(exactMatch);
      } catch {
        // Exact ticker lookup is best-effort; fallback search still covers names.
      }
    }

    try {
      const rows = await fetchJson<USStockMasterRead[]>("/api/us-market/stocks/search", {
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
    const symbol = normalizeTickerInput(symbolInput);
    if (!symbol || selectedGroupId === null) return;

    await runAction(
      async () => {
        const item = await requestJson<USWatchlistItemRead>(
          "/api/us-market/watchlists/items",
          {
            method: "POST",
            body: JSON.stringify({
              group_id: selectedGroupId,
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
        onSelectSymbol(item.symbol, item.security_name);
      },
      "已新增美股自選股"
    );
  }

  async function deleteStockItem(item: USWatchlistItemRead) {
    const confirmed = window.confirm(`刪除 ${item.symbol}？`);
    if (!confirmed) return;

    await runAction(
      async () => {
        await deleteRequest(`/api/us-market/watchlists/items/${item.id}`);
      },
      "已刪除美股自選股"
    );
  }

  async function toggleStockItem(item: USWatchlistItemRead) {
    await runAction(
      async () => {
        await requestJson<USWatchlistItemRead>(
          `/api/us-market/watchlists/items/${item.id}`,
          {
            method: "PATCH",
            body: JSON.stringify({ enabled: !item.enabled }),
          }
        );
      },
      item.enabled ? "已停用美股自選股" : "已啟用美股自選股"
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
    const selected = US_MARKET_INDEX_ITEMS.some((item) => item.symbol === selectedSymbol);

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
            aria-label="切換美股指數資料夾"
          >
            {indexGroupExpanded ? "v" : ">"}
          </button>

          <div className="min-w-0 flex-1 text-left">
            <div className="truncate font-semibold">{US_MARKET_INDEX_GROUP_NAME}</div>
          </div>

          <span className={selected ? "pr-2 text-xs text-omi-accent" : "pr-2 text-xs text-omi-text-subtle"}>
            {US_MARKET_INDEX_ITEMS.length}
          </span>
        </div>

        {indexGroupExpanded ? (
          <div>
            {US_MARKET_INDEX_ITEMS.map((item) => {
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
                      {item.exchange} · index · {item.note}
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

  function renderGroupNode(node: USWatchlistGroupNode, depth = 0) {
    const selected = node.id === selectedGroupId;
    const expanded = expandedIds.has(node.id);
    const childItems = itemsByGroupId.get(node.id) ?? [];
    const hasChildren = node.children.length > 0 || childItems.length > 0;

    return (
      <div key={node.id}>
        <div
          className={[
            "relative flex cursor-pointer items-center gap-1 py-1 pr-1 text-sm",
            selected ? "omi-sidebar-selected text-omi-text-strong" : "text-omi-text-muted hover:bg-omi-surface-muted",
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
                    onMouseDown={(event) =>
                      selectOnPrimaryMouseDown(event, () =>
                        onSelectSymbol(item.symbol, item.security_name)
                      )
                    }
                    onClick={() => onSelectSymbol(item.symbol, item.security_name)}
                  >
                    <div className="truncate font-semibold">
                      {item.symbol} {item.security_name ?? ""}
                    </div>
                    <div className={itemSelected ? "truncate text-omi-text-muted" : "truncate text-omi-text-subtle"}>
                      {[item.exchange, item.asset_type, item.note].filter(Boolean).join(" · ")}
                    </div>
                  </button>
                  <button
                    type="button"
                    className={[
                      "hidden px-1.5 py-0.5 text-[10px] font-semibold group-hover:block",
                      itemSelected ? "bg-omi-surface text-omi-text" : "bg-omi-surface-strong text-omi-text-muted",
                    ].join(" ")}
                    onClick={() => void toggleStockItem(item)}
                  >
                    {item.enabled ? "off" : "on"}
                  </button>
                  <button
                    type="button"
                    className="hidden bg-omi-danger-soft px-1.5 py-0.5 text-[10px] font-semibold text-omi-danger group-hover:block"
                    onClick={() => void deleteStockItem(item)}
                  >
                    x
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
    <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-omi-border-subtle bg-omi-surface">
      <div className="border-b border-omi-border-subtle px-4 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.22em] text-omi-accent">
          Open Market Intelligence
        </div>
        <h1 className="mt-2 text-xl font-bold text-omi-text-strong">Market Dashboard</h1>
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
              {option.label}
            </a>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between border-b border-omi-border-subtle px-4 py-3">
        <div>
          <div className="text-xs font-semibold text-omi-text-muted">美股自選</div>
          <div className="text-sm font-bold text-omi-text-strong">
            {selectedGroup?.group_name ?? "尚未建立分組"}
          </div>
        </div>
        <button
          type="button"
          className={buttonClass("ghost")}
          onClick={() => void reloadSidebarData()}
          disabled={loading}
        >
          Reload
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {renderPinnedIndexGroup()}
        {tree.length > 0 ? (
          tree.map((node) => renderGroupNode(node))
        ) : (
          <div className="px-4 py-6 text-sm text-omi-text-muted">尚未建立美股分組</div>
        )}
      </div>

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
        <JobStatusCenter placement="inline" market="us" />
      </div>

      <div className="space-y-4 p-4">
        <form
          action="/"
          method="post"
          onSubmit={handleFolderSubmit}
        >
          <div className="mb-2 text-xs font-bold text-omi-text-muted">分組管理</div>
          <input
            className={inputClass()}
            name="group_name"
            placeholder="新增分組名稱"
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
              + Root
            </button>
            <button
              type="submit"
              name="intent"
              value="create_child"
              className={buttonClass("primary")}
              disabled={loading || selectedGroupId === null}
            >
              + Child
            </button>
          </div>
        </form>

        <form
          action="/"
          method="post"
          onSubmit={handleSelectedFolderSubmit}
          className="space-y-2"
        >
          <input
            className={inputClass()}
            name="group_name"
            placeholder="重新命名目前分組"
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
              Rename
            </button>
            <button
              type="submit"
              name="intent"
              value="delete"
              className={buttonClass("danger")}
              disabled={loading || selectedGroupId === null}
            >
              Delete
            </button>
          </div>
        </form>

        <div className="space-y-2">
          <form
            id="us-watchlist-stock-form"
            action="/"
            method="post"
            onSubmit={handleStockSubmit}
            className="space-y-2"
          >
            <div className="text-xs font-bold text-omi-text-muted">加入股票</div>
            <div className="flex gap-2">
              <input
                className={inputClass()}
                name="symbol"
                placeholder="AAPL / Apple"
                value={symbolInput}
                onChange={(event) => setSymbolInput(event.target.value)}
              />
              <button
                type="button"
                className={buttonClass("ghost")}
                onClick={() => void findStockSuggestions()}
                disabled={loading}
              >
                Find
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
                    {stock.symbol} {stock.security_name ?? stock.sec_company_name ?? ""} · {stock.exchange ?? "-"}
                  </button>
                ))}
              </div>
            ) : null}
            <input
              className={inputClass()}
              name="note"
              placeholder="備註"
              value={stockNote}
              onChange={(event) => setStockNote(event.target.value)}
            />
            <input
              className={inputClass()}
              name="tags"
              placeholder="標籤，例如 ETF,core"
              value={stockTags}
              onChange={(event) => setStockTags(event.target.value)}
            />
          </form>
          <div className="flex items-center justify-between gap-2">
            <button
              type="submit"
              form="us-watchlist-stock-form"
              className={buttonClass("primary")}
              disabled={loading || selectedGroupId === null}
            >
              + Stock
            </button>
            <SettingsDock placement="inline" />
          </div>
        </div>
      </div>
    </aside>
  );
}

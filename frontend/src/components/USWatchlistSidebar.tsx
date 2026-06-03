"use client";

import type { MarketRegion } from "@/components/SidebarWatchlistExplorer";
import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type {
  USStockMasterRead,
  USWatchlistGroupNode,
  USWatchlistGroupRead,
  USWatchlistItemRead,
} from "@/types/market";
import { FormEvent, useMemo, useState } from "react";

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
  return "h-9 w-full border border-slate-300 bg-white px-3 text-sm text-slate-800 outline-none transition focus:border-red-700";
}

function buttonClass(kind: "primary" | "ghost" | "danger" = "ghost") {
  if (kind === "primary") {
    return "h-8 bg-red-700 px-3 text-xs font-semibold text-white hover:bg-red-800 disabled:cursor-not-allowed disabled:bg-slate-300";
  }

  if (kind === "danger") {
    return "h-8 bg-red-50 px-3 text-xs font-semibold text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:text-slate-300";
  }

  return "h-8 bg-slate-100 px-3 text-xs font-semibold text-slate-700 hover:bg-slate-200 disabled:cursor-not-allowed disabled:text-slate-300";
}

function submitterValue(event: FormEvent<HTMLFormElement>) {
  const nativeEvent = event.nativeEvent as SubmitEvent;
  const submitter = nativeEvent.submitter as HTMLButtonElement | null;
  return submitter?.value ?? "";
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

  function renderGroupNode(node: USWatchlistGroupNode, depth = 0) {
    const selected = node.id === selectedGroupId;
    const expanded = expandedIds.has(node.id);
    const childItems = itemsByGroupId.get(node.id) ?? [];
    const hasChildren = node.children.length > 0 || childItems.length > 0;

    return (
      <div key={node.id}>
        <div
          className={[
            "flex cursor-pointer items-center gap-1 py-1 pr-1 text-sm",
            selected ? "bg-red-700 text-white" : "text-slate-700 hover:bg-slate-100",
          ].join(" ")}
          style={{ paddingLeft: `${4 + depth * 16}px` }}
          onClick={() => selectGroup(node)}
        >
          <button
            type="button"
            className={selected ? "h-6 w-4 text-xs text-white" : "h-6 w-4 text-xs text-slate-500"}
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
          <span className={selected ? "pr-2 text-xs text-red-100" : "pr-2 text-xs text-slate-400"}>
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
                    "group flex items-center gap-1 py-1.5 pr-2 text-xs",
                    itemSelected
                      ? "bg-slate-900 text-white"
                      : "text-slate-700 hover:bg-slate-100",
                  ].join(" ")}
                  style={{ paddingLeft: `${24 + depth * 16}px` }}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => onSelectSymbol(item.symbol, item.security_name)}
                  >
                    <div className="truncate font-semibold">
                      {item.symbol} {item.security_name ?? ""}
                    </div>
                    <div className={itemSelected ? "truncate text-slate-300" : "truncate text-slate-400"}>
                      {[item.exchange, item.asset_type, item.note].filter(Boolean).join(" · ")}
                    </div>
                  </button>
                  <button
                    type="button"
                    className={[
                      "hidden px-1.5 py-0.5 text-[10px] font-semibold group-hover:block",
                      itemSelected ? "bg-white text-slate-900" : "bg-slate-200 text-slate-700",
                    ].join(" ")}
                    onClick={() => void toggleStockItem(item)}
                  >
                    {item.enabled ? "off" : "on"}
                  </button>
                  <button
                    type="button"
                    className="hidden bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 group-hover:block"
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
    <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.22em] text-red-700">
          Open Market Intelligence
        </div>
        <h1 className="mt-2 text-xl font-bold text-slate-950">Market Dashboard</h1>
        <div className="mt-3 grid grid-cols-5 border border-slate-200 bg-slate-50 p-1">
          {marketOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                if (option.enabled) onMarketChange(option.value);
              }}
              disabled={!option.enabled}
              className={[
                "h-8 text-xs font-semibold transition",
                selectedMarket === option.value
                  ? "bg-red-700 text-white"
                  : option.enabled
                    ? "text-slate-600 hover:bg-white"
                    : "cursor-not-allowed text-slate-300",
              ].join(" ")}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <div className="text-xs font-semibold text-slate-500">美股自選</div>
          <div className="text-sm font-bold text-slate-950">
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
        {tree.length > 0 ? (
          tree.map((node) => renderGroupNode(node))
        ) : (
          <div className="px-4 py-6 text-sm text-slate-500">尚未建立美股分組</div>
        )}
      </div>

      {message ? (
        <div
          className={[
            "mx-4 mb-3 border px-3 py-2 text-xs",
            message.type === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700",
          ].join(" ")}
        >
          {message.text}
        </div>
      ) : null}

      <div className="space-y-4 p-4">
        <form
          action="/"
          method="post"
          onSubmit={handleFolderSubmit}
        >
          <div className="mb-2 text-xs font-bold text-slate-600">分組管理</div>
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

        <form
          action="/"
          method="post"
          onSubmit={handleStockSubmit}
          className="space-y-2"
        >
          <div className="text-xs font-bold text-slate-600">加入股票</div>
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
            <div className="max-h-28 overflow-y-auto border border-slate-200 bg-white">
              {stockSuggestions.map((stock) => (
                <button
                  key={stock.symbol}
                  type="button"
                  className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-slate-100"
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
          <button
            type="submit"
            className={buttonClass("primary")}
            disabled={loading || selectedGroupId === null}
          >
            + Stock
          </button>
        </form>
      </div>
    </aside>
  );
}

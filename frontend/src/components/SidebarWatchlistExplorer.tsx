"use client";

import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type {
  StockMasterRead,
  WatchlistGroupNode,
  WatchlistGroupRead,
  WatchlistItemRead,
} from "@/types/market";
import { FormEvent, useEffect, useMemo, useState } from "react";

type Props = {
  initialTree: WatchlistGroupNode[];
  initialItems: WatchlistItemRead[];
  selectedGroupId: number | null;
  selectedStockId: string | null;
  onSelectGroup: (group: WatchlistGroupNode | null) => void;
  onSelectStock: (stockId: string, stockName: string | null) => void;
  onChanged: (nextGroupId?: number | null) => Promise<void> | void;
};

type Message = { type: "success" | "error"; text: string } | null;

function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
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

export default function SidebarWatchlistExplorer({
  initialTree,
  initialItems,
  selectedGroupId,
  selectedStockId,
  onSelectGroup,
  onSelectStock,
  onChanged,
}: Props) {
  const [tree, setTree] = useState<WatchlistGroupNode[]>(initialTree);
  const [items, setItems] = useState<WatchlistItemRead[]>(initialItems);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(
    new Set(initialTree.map((group) => group.id))
  );
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [folderName, setFolderName] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [stockInput, setStockInput] = useState("");
  const [stockNote, setStockNote] = useState("");
  const [stockTags, setStockTags] = useState("");
  const [stockSuggestions, setStockSuggestions] = useState<StockMasterRead[]>([]);

  const allGroups = useMemo(() => flattenGroups(tree), [tree]);
  const selectedGroup = useMemo(() => {
    return allGroups.find((group) => group.id === selectedGroupId) ?? null;
  }, [allGroups, selectedGroupId]);

  const itemsByGroupId = useMemo(() => {
    const map = new Map<number, WatchlistItemRead[]>();

    items.forEach((item) => {
      const list = map.get(item.group_id) ?? [];
      list.push(item);
      map.set(item.group_id, list);
    });

    return map;
  }, [items]);

  async function reloadExplorerData(options?: { keepSelection?: boolean }) {
    const [treeData, itemData] = await Promise.all([
      fetchJson<WatchlistGroupNode[]>("/api/watchlists/tree"),
      fetchJson<WatchlistItemRead[]>("/api/watchlists/items", {
        limit: 1000,
        offset: 0,
      }),
    ]);

    setTree(treeData);
    setItems(itemData);

    const flattened = flattenGroups(treeData);

    setExpandedIds((previous) => {
      const next = new Set(previous);
      treeData.forEach((root) => next.add(root.id));
      if (selectedGroupId !== null) next.add(selectedGroupId);
      return next;
    });

    const selectedStillExists =
      selectedGroupId !== null &&
      flattened.some((group) => group.id === selectedGroupId);

    if (options?.keepSelection && selectedStillExists) {
      const currentGroup =
        flattened.find((group) => group.id === selectedGroupId) ?? null;
      onSelectGroup(currentGroup);
      setRenameValue(currentGroup?.group_name ?? "");
      return currentGroup;
    }

    const nextGroup = flattened[0] ?? null;
    onSelectGroup(nextGroup);
    setRenameValue(nextGroup?.group_name ?? "");
    return nextGroup;
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
        text: error instanceof Error ? error.message : "操作失敗",
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setTree(initialTree);
      setItems(initialItems);
    }, 0);

    return () => window.clearTimeout(timer);
  }, [initialTree, initialItems]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      reloadExplorerData({ keepSelection: true }).catch((error) => {
        setMessage({
          type: "error",
          text: error instanceof Error ? error.message : "自選股讀取失敗",
        });
      });
    }, 0);

    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  async function createRootFolder() {
    const name = folderName.trim();
    if (!name) {
      setMessage({ type: "error", text: "請輸入分組名稱" });
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
      "已新增分組",
      { keepSelection: false }
    );
  }

  async function createChildFolder() {
    const name = folderName.trim();
    if (selectedGroupId === null) {
      setMessage({ type: "error", text: "請先選擇分組" });
      return;
    }
    if (!name) {
      setMessage({ type: "error", text: "請輸入分組名稱" });
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
      "已新增子分組",
      { keepSelection: true }
    );
  }

  async function renameSelectedFolder() {
    const name = renameValue.trim();
    if (selectedGroupId === null || !selectedGroup) {
      setMessage({ type: "error", text: "請先選擇分組" });
      return;
    }
    if (!name) {
      setMessage({ type: "error", text: "請輸入新名稱" });
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
      "已重新命名分組",
      { keepSelection: true }
    );
  }

  async function deleteSelectedFolder() {
    if (selectedGroupId === null || !selectedGroup) {
      setMessage({ type: "error", text: "請先選擇分組" });
      return;
    }

    const confirmed = window.confirm(`刪除分組「${selectedGroup.group_name}」與其內容？`);
    if (!confirmed) return;

    await runAction(
      async () => {
        await deleteRequest(`/api/watchlists/groups/${selectedGroupId}`, {
          recursive: true,
        });
      },
      "已刪除分組",
      { keepSelection: false }
    );
  }

  async function createStockItem() {
    const value = stockInput.trim().toUpperCase();
    if (selectedGroupId === null) {
      setMessage({ type: "error", text: "請先選擇分組" });
      return;
    }
    if (!value) {
      setMessage({ type: "error", text: "請輸入股票代號" });
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
      "已加入自選股",
      { keepSelection: true }
    );
  }

  async function deleteStockItem(item: WatchlistItemRead) {
    const confirmed = window.confirm(`刪除 ${item.stock_id} ${item.stock_name ?? ""}？`);
    if (!confirmed) return;

    await runAction(
      async () => {
        await deleteRequest(`/api/watchlists/items/${item.id}`);
      },
      "已刪除自選股",
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
      item.enabled ? "已停用自選股" : "已啟用自選股",
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

  function renderGroupNode(node: WatchlistGroupNode, depth = 0) {
    const selected = node.id === selectedGroupId;
    const expanded = expandedIds.has(node.id);
    const children = node.children;
    const groupItems = itemsByGroupId.get(node.id) ?? [];
    const hasContent = children.length > 0 || groupItems.length > 0;

    return (
      <div key={node.id}>
        <div
          className={[
            "flex items-center gap-1 py-1 pr-1 text-sm",
            selected ? "bg-red-700 text-white" : "text-slate-700 hover:bg-slate-100",
          ].join(" ")}
          style={{ paddingLeft: `${8 + depth * 14}px` }}
        >
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              toggleExpanded(node.id);
            }}
            className={[
              "h-6 w-6 text-xs",
              selected ? "text-white" : "text-slate-500",
              !hasContent ? "opacity-40" : "",
            ].join(" ")}
          >
            {hasContent ? (expanded ? "v" : ">") : "-"}
          </button>

          <button
            type="button"
            onClick={() => selectGroup(node)}
            className="min-w-0 flex-1 text-left"
          >
            <div className="truncate font-semibold">{node.group_name}</div>
          </button>

          <span className={selected ? "pr-2 text-xs text-red-100" : "pr-2 text-xs text-slate-400"}>
            {groupItems.length}
          </span>
        </div>

        {expanded ? (
          <div>
            {groupItems.map((item) => {
              const itemSelected = item.stock_id === selectedStockId;

              return (
                <div
                  key={item.id}
                  className={[
                    "group flex cursor-pointer items-center gap-2 py-1.5 pr-2 text-xs",
                    itemSelected
                      ? "bg-slate-900 text-white"
                      : item.enabled
                        ? "text-slate-700 hover:bg-slate-100"
                        : "text-slate-400",
                  ].join(" ")}
                  style={{ paddingLeft: `${38 + depth * 14}px` }}
                  onClick={() => onSelectStock(item.stock_id, item.stock_name)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold">
                      {item.stock_id} {item.stock_name ?? ""}
                    </div>
                    {item.tags || item.note ? (
                      <div className={itemSelected ? "truncate text-slate-300" : "truncate text-slate-400"}>
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
                      onClick={(event) => event.stopPropagation()}
                      className={[
                        "hidden px-1.5 py-0.5 text-[10px] font-semibold group-hover:block",
                        itemSelected ? "bg-white text-slate-900" : "bg-slate-200 text-slate-700",
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
                      onClick={(event) => event.stopPropagation()}
                      className="hidden bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 group-hover:block"
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
    <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.22em] text-red-700">
          Open Market Intelligence
        </div>
        <h1 className="mt-2 text-xl font-bold text-slate-950">Market Dashboard</h1>
      </div>

      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <div className="text-xs font-semibold text-slate-500">自選股</div>
          <div className="text-sm font-bold text-slate-950">
            {selectedGroup?.group_name ?? "尚未選擇"}
          </div>
        </div>
        <button
          type="button"
          className={buttonClass("ghost")}
          onClick={() => void reloadExplorerData({ keepSelection: true })}
          disabled={loading}
        >
          重新整理
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {tree.length > 0 ? (
          tree.map((node) => renderGroupNode(node))
        ) : (
          <div className="px-4 py-6 text-sm text-slate-500">尚未建立分組</div>
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

      <div className="space-y-4 border-t border-slate-200 p-4">
        <form
          action="/omi-form/watchlists/groups"
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
          <input type="hidden" name="parent_id" value={selectedGroupId ?? ""} />
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
          action="/omi-form/watchlists/groups"
          method="post"
          onSubmit={handleSelectedFolderSubmit}
          className="space-y-2"
        >
          <input type="hidden" name="group_id" value={selectedGroupId ?? ""} />
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
          action="/omi-form/watchlists/items"
          method="post"
          onSubmit={handleStockSubmit}
          className="space-y-2"
        >
          <div className="text-xs font-bold text-slate-600">加入股票</div>
          <input type="hidden" name="intent" value="create" />
          <input type="hidden" name="group_id" value={selectedGroupId ?? ""} />
          <input
            className={inputClass()}
            name="stock_id"
            placeholder="股票代號或名稱，例如 2330"
            value={stockInput}
            onChange={(event) => setStockInput(event.target.value)}
          />
          {stockSuggestions.length > 0 ? (
            <div className="max-h-28 overflow-y-auto border border-slate-200 bg-white">
              {stockSuggestions.map((stock) => (
                <button
                  key={stock.stock_id}
                  type="button"
                  className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-slate-100"
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

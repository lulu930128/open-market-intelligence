"use client";

import { useEffect, useMemo, useState } from "react";
import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type {
  WatchlistGroupNode,
  WatchlistGroupRead,
  WatchlistItemRead,
} from "@/types/market";

type Props = {
  selectedGroupId: number | null;
  onSelectGroup: (group: WatchlistGroupNode | null) => void;
  onChanged: (nextGroupId?: number | null) => Promise<void> | void;
};

type Message =
  | {
      type: "success" | "error";
      text: string;
    }
  | null;


type WatchlistGroupBackfillResult = {
  group_id: number;
  include_children: boolean;
  start_date: string;
  end_date: string;
  requested_stock_count: number;
  success_count: number;
  warning_count: number;
  error_count: number;
  skipped_count: number;
  results: {
    stock_id: string;
    stock_name: string | null;
    status: string;
    parsed_count: number;
    inserted_count: number;
    skipped_count: number;
    message: string | null;
    error_message: string | null;
  }[];
};


function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
}

function inputClass() {
  return "w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm outline-none focus:border-indigo-400";
}

function smallButtonClass(kind: "primary" | "secondary" | "danger" = "secondary") {
  if (kind === "primary") {
    return "rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700";
  }

  if (kind === "danger") {
    return "rounded-lg bg-rose-100 px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-200";
  }

  return "rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-200";
}

function toDateInputValue(date: Date) {
  return date.toISOString().slice(0, 10);
}

function getDefaultBackfillStartDate() {
  const date = new Date();
  date.setMonth(date.getMonth() - 3);
  return toDateInputValue(date);
}

function getTodayDate() {
  return toDateInputValue(new Date());
}

export default function SidebarWatchlistExplorer({
  selectedGroupId,
  onSelectGroup,
  onChanged,
}: Props) {
  const [tree, setTree] = useState<WatchlistGroupNode[]>([]);
  const [items, setItems] = useState<WatchlistItemRead[]>([]);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const [message, setMessage] = useState<Message>(null);
  const [loading, setLoading] = useState(false);

  const [folderName, setFolderName] = useState("");
  const [stockId, setStockId] = useState("");
  const [stockNote, setStockNote] = useState("");
  const [stockTags, setStockTags] = useState("");

  const [backfillStartDate, setBackfillStartDate] = useState(
    getDefaultBackfillStartDate()
  );
  const [backfillEndDate, setBackfillEndDate] = useState(getTodayDate());

  const [renameValue, setRenameValue] = useState("");

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

      if (selectedGroupId !== null) {
        next.add(selectedGroupId);
      }

      return next;
    });

    const selectedStillExists =
      selectedGroupId !== null &&
      flattened.some((group) => group.id === selectedGroupId);

    if (!options?.keepSelection || !selectedStillExists) {
      const nextGroup = flattened[0] ?? null;

      onSelectGroup(nextGroup);
      setRenameValue(nextGroup?.group_name ?? "");

      return nextGroup;
    }

    const currentGroup =
      flattened.find((group) => group.id === selectedGroupId) ?? null;

    if (currentGroup) {
      onSelectGroup(currentGroup);
      setRenameValue(currentGroup.group_name);
    }

    return currentGroup;
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
        text: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reloadExplorerData().catch((error) => {
      setMessage({
        type: "error",
        text:
          error instanceof Error
            ? error.message
            : "Failed to load watchlist explorer.",
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedGroup) {
      setRenameValue(selectedGroup.group_name);
    }
  }, [selectedGroup]);

  function toggleExpanded(groupId: number) {
    setExpandedIds((previous) => {
      const next = new Set(previous);

      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }

      return next;
    });
  }

  function selectGroup(group: WatchlistGroupNode) {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      next.add(group.id);
      return next;
    });

    onSelectGroup(group);
    setRenameValue(group.group_name);
  }
  
  async function createRootFolder() {
    const name = folderName.trim();

    if (!name) {
      setMessage({ type: "error", text: "資料夾名稱不可為空。" });
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
      "已新增根資料夾。",
      { keepSelection: false }
    );
  }

  async function createChildFolder() {
    const name = folderName.trim();
    const parentId = selectedGroupId;

    if (parentId === null) {
      setMessage({ type: "error", text: "請先選擇一個資料夾。" });
      return;
    }

    if (!name) {
      setMessage({ type: "error", text: "資料夾名稱不可為空。" });
      return;
    }

    await runAction(
      async () => {
        await requestJson<WatchlistGroupRead>("/api/watchlists/groups", {
          method: "POST",
          body: JSON.stringify({
            parent_id: parentId,
            group_name: name,
            description: null,
            sort_order: 100,
            is_active: true,
          }),
        });

        setFolderName("");

        setExpandedIds((previous) => {
          const next = new Set(previous);
          next.add(parentId);
          return next;
        });
      },
      "已新增子資料夾。",
      { keepSelection: true }
    );
  }

  async function renameSelectedFolder() {
    const name = renameValue.trim();
    const groupId = selectedGroupId;

    if (groupId === null || !selectedGroup) {
      setMessage({ type: "error", text: "請先選擇一個資料夾。" });
      return;
    }

    if (!name) {
      setMessage({ type: "error", text: "資料夾名稱不可為空。" });
      return;
    }

    if (name === selectedGroup.group_name) {
      return;
    }

    await runAction(
      async () => {
        await requestJson<WatchlistGroupRead>(`/api/watchlists/groups/${groupId}`, {
          method: "PATCH",
          body: JSON.stringify({
            group_name: name,
          }),
        });
      },
      "已重新命名資料夾。",
      { keepSelection: true }
    );
  }

  async function deleteSelectedFolder() {
    const groupId = selectedGroupId;

    if (groupId === null || !selectedGroup) {
      setMessage({ type: "error", text: "請先選擇一個資料夾。" });
      return;
    }

    const confirmed = window.confirm(
      `確定要刪除「${selectedGroup.group_name}」嗎？\n\n此操作會一併刪除底下所有子資料夾與股票，無法復原。`
    );

    if (!confirmed) return;

    await runAction(
      async () => {
        await deleteRequest(`/api/watchlists/groups/${groupId}`, {
          recursive: true,
        });
      },
      "已刪除資料夾。",
      { keepSelection: false }
    );
  }

  async function createStockItem() {
    const value = stockId.trim();
    const groupId = selectedGroupId;

    if (groupId === null) {
      setMessage({ type: "error", text: "請先選擇一個資料夾。" });
      return;
    }

    if (!value) {
      setMessage({ type: "error", text: "請輸入股票代號。" });
      return;
    }

    await runAction(
      async () => {
        await requestJson<WatchlistItemRead>("/api/watchlists/items", {
          method: "POST",
          body: JSON.stringify({
            group_id: groupId,
            stock_id: value,
            note: stockNote.trim() || null,
            priority: 100,
            tags: stockTags.trim() || null,
            enabled: true,
          }),
        });

        setStockId("");
        setStockNote("");
        setStockTags("");

        setExpandedIds((previous) => {
          const next = new Set(previous);
          next.add(groupId);
          return next;
        });
      },
      "已加入自選股。",
      { keepSelection: true }
    );
  }


  async function backfillSelectedFolder() {
    if (selectedGroupId === null || !selectedGroup) {
      setMessage({ type: "error", text: "請先選擇一個資料夾。" });
      return;
    }

    const confirmed = window.confirm(
      `確定要補「${selectedGroup.group_name}」底下所有啟用股票的歷史資料嗎？\n\n範圍：${backfillStartDate} ~ ${backfillEndDate}`
    );

    if (!confirmed) return;

    await runAction(
      async () => {
        const result = await requestJson<WatchlistGroupBackfillResult>(
          `/api/watchlists/groups/${selectedGroupId}/backfill/twse`,
          {
            method: "POST",
          },
          {
            start_date: backfillStartDate,
            end_date: backfillEndDate,
            source_id: 1,
            include_children: true,
            enabled_only: true,
            sleep_seconds: 0.8,
          }
        );

        if (result.error_count > 0) {
          throw new Error(
            `Backfill completed with ${result.error_count} error(s). Success: ${result.success_count}, requested: ${result.requested_stock_count}`
          );
        }
      },
      "已完成此資料夾的歷史資料補齊。",
      { keepSelection: true }
    );
  }


  async function deleteStockItem(item: WatchlistItemRead) {
    const confirmed = window.confirm(
      `確定要刪除 ${item.stock_id} ${item.stock_name ?? ""} 嗎？`
    );

    if (!confirmed) return;

    await runAction(
      async () => {
        await deleteRequest(`/api/watchlists/items/${item.id}`);
      },
      "已刪除自選股。",
      { keepSelection: true }
    );
  }

  async function toggleStockItem(item: WatchlistItemRead) {
    await runAction(
      async () => {
        await requestJson<WatchlistItemRead>(`/api/watchlists/items/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            enabled: !item.enabled,
          }),
        });
      },
      item.enabled ? "已停用自選股。" : "已啟用自選股。",
      { keepSelection: true }
    );
  }

  function renderGroupNode(node: WatchlistGroupNode, depth = 0) {
    const selected = node.id === selectedGroupId;
    const expanded = expandedIds.has(node.id);
    const children = node.children;
    const groupItems = itemsByGroupId.get(node.id) ?? [];

    return (
      <div key={node.id}>
        <div
          className={[
            "group flex items-center gap-1 rounded-xl py-1.5 pr-2 text-sm transition",
            selected
              ? "bg-indigo-600 text-white shadow-sm"
              : "text-slate-600 hover:bg-white",
          ].join(" ")}
          style={{ paddingLeft: `${8 + depth * 16}px` }}
        >
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              toggleExpanded(node.id);
            }}
            className={[
              "flex h-5 w-5 items-center justify-center rounded text-xs",
              selected
                ? "text-white hover:bg-indigo-500"
                : "text-slate-400 hover:bg-slate-100",
            ].join(" ")}
          >
            {children.length > 0 || groupItems.length > 0
              ? expanded
                ? "▾"
                : "▸"
              : "·"}
          </button>

          <button
            type="button"
            onClick={() => selectGroup(node)}
            className="min-w-0 flex-1 text-left"
          >
            <div className="truncate font-medium">{node.group_name}</div>

            {node.description ? (
              <div
                className={[
                  "truncate text-xs",
                  selected ? "text-indigo-100" : "text-slate-400",
                ].join(" ")}
              >
                {node.description}
              </div>
            ) : null}
          </button>
        </div>

        {expanded ? (
          <div className="mt-1 space-y-1">
            {groupItems.map((item) => (
              <div
                key={item.id}
                className={[
                  "group flex items-center gap-2 rounded-lg py-1.5 pr-2 text-xs",
                  item.enabled
                    ? "text-slate-500 hover:bg-white"
                    : "text-slate-300",
                ].join(" ")}
                style={{ paddingLeft: `${34 + depth * 16}px` }}
              >
                <span className="text-slate-300">●</span>

                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">
                    {item.stock_id} {item.stock_name ?? ""}
                  </div>

                  {item.tags || item.note ? (
                    <div className="truncate text-slate-400">
                      {item.tags || item.note}
                    </div>
                  ) : null}
                </div>

                <button
                  type="button"
                  onClick={() => void toggleStockItem(item)}
                  className="hidden rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 group-hover:inline"
                >
                  {item.enabled ? "off" : "on"}
                </button>

                <button
                  type="button"
                  onClick={() => void deleteStockItem(item)}
                  className="hidden rounded bg-rose-100 px-1.5 py-0.5 text-[10px] text-rose-600 group-hover:inline"
                >
                  del
                </button>
              </div>
            ))}

            {children.map((child) => renderGroupNode(child, depth + 1))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <aside className="h-full w-80 shrink-0 overflow-y-auto rounded-3xl border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur">
      <div className="mb-5">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-500">
          Open Market Intelligence
        </p>

        <h1 className="mt-2 text-2xl font-bold tracking-tight">
          Market Dashboard
        </h1>

        <p className="mt-2 text-sm leading-6 text-slate-500">
          左側管理自選股，右側查看排名、訊號與指標。
        </p>
      </div>

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">
          Watchlist Explorer
        </h2>

        <button
          type="button"
          onClick={() => void reloadExplorerData({ keepSelection: true })}
          className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
        >
          Refresh
        </button>
      </div>

      <div className="space-y-1">{tree.map((node) => renderGroupNode(node))}</div>

      {message ? (
        <div
          className={[
            "mt-4 rounded-2xl border p-3 text-xs",
            message.type === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-rose-200 bg-rose-50 text-rose-700",
          ].join(" ")}
        >
          {message.text}
        </div>
      ) : null}

      <div className="mt-5 rounded-2xl bg-slate-50 p-4">
        <p className="text-xs font-semibold text-slate-500">Selected Folder</p>

        <p className="mt-1 truncate text-sm font-bold text-slate-800">
          {selectedGroup?.group_name ?? "未選擇"}
        </p>

        <div className="mt-3 space-y-2">
          <input
            className={inputClass()}
            placeholder="重新命名資料夾"
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
          />

          <div className="flex gap-2">
            <button
              type="button"
              className={smallButtonClass("primary")}
              disabled={loading || selectedGroupId === null}
              onClick={() => void renameSelectedFolder()}
            >
              Rename
            </button>

            <button
              type="button"
              className={smallButtonClass("danger")}
              disabled={loading || selectedGroupId === null}
              onClick={() => void deleteSelectedFolder()}
            >
              Delete
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-2xl bg-slate-50 p-4">
      <p className="text-xs font-semibold text-slate-500">Add Folder</p>

      <div className="mt-3 space-y-2">
          <input
          className={inputClass()}
          placeholder="例如：ETF / AI Server / PCB"
          value={folderName}
          onChange={(event) => setFolderName(event.target.value)}
          />

          <div className="flex gap-2">
          <button
              type="button"
              className={smallButtonClass("secondary")}
              disabled={loading}
              onClick={() => void createRootFolder()}
          >
              + Root
          </button>

          <button
              type="button"
              className={smallButtonClass("primary")}
              disabled={loading || selectedGroupId === null}
              onClick={() => void createChildFolder()}
          >
              + Child
          </button>
          </div>

          <p className="text-[11px] leading-5 text-slate-400">
          Root 會建立最上層資料夾；Child 會建立在目前選取的資料夾底下。
          </p>
      </div>
    </div>
    
      <div className="mt-4 rounded-2xl bg-slate-50 p-4">
        <p className="text-xs font-semibold text-slate-500">Add Stock</p>

        <div className="mt-3 space-y-2">
          <input
            className={inputClass()}
            placeholder="股票代號，例如：2330"
            value={stockId}
            onChange={(event) => setStockId(event.target.value)}
          />

          <input
            className={inputClass()}
            placeholder="Note"
            value={stockNote}
            onChange={(event) => setStockNote(event.target.value)}
          />

          <input
            className={inputClass()}
            placeholder="Tags，例如：ETF,core"
            value={stockTags}
            onChange={(event) => setStockTags(event.target.value)}
          />

          <button
            type="button"
            className={smallButtonClass("primary")}
            disabled={loading || selectedGroupId === null}
            onClick={() => void createStockItem()}
          >
            + Stock
          </button>
        </div>
      </div>

      <div className="mt-4 rounded-2xl bg-slate-50 p-4">
        <p className="text-xs font-semibold text-slate-500">Backfill Selected Folder</p>

        <div className="mt-3 space-y-2">
            <input
            className={inputClass()}
            type="date"
            value={backfillStartDate}
            onChange={(event) => setBackfillStartDate(event.target.value)}
            />

            <input
            className={inputClass()}
            type="date"
            value={backfillEndDate}
            onChange={(event) => setBackfillEndDate(event.target.value)}
            />

            <button
            type="button"
            className={smallButtonClass("primary")}
            disabled={loading || selectedGroupId === null}
            onClick={() => void backfillSelectedFolder()}
            >
            Backfill
            </button>

            <p className="text-[11px] leading-5 text-slate-400">
            會補目前資料夾與子資料夾底下所有啟用股票的 TWSE 歷史日資料。
            </p>
        </div>
        </div>
    </aside>
  );
}
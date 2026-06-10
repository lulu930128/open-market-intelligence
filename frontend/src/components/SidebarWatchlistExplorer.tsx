"use client";

import JobStatusCenter from "@/components/JobStatusCenter";
import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type {
  StockMasterRead,
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
  selectedMarket: MarketRegion;
  onSelectGroup: (group: WatchlistGroupNode | null) => void;
  onSelectStock: (stockId: string, stockName: string | null) => void;
  onMarketChange: (market: MarketRegion) => void;
  onExplorerDataChanged?: (
    tree: WatchlistGroupNode[],
    items: WatchlistItemRead[]
  ) => void;
  onChanged: (nextGroupId?: number | null) => Promise<void> | void;
};

type Message = { type: "success" | "error"; text: string } | null;
export type MarketRegion = "tw" | "us" | "jp" | "kr" | "hk";
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

type SidebarMarketOption = {
  label: string;
  value: MarketRegion;
  enabled: boolean;
  summary: string;
};

const sidebarMarketOptions: SidebarMarketOption[] = [
  { label: "台股", value: "tw", enabled: true, summary: "自選股 / 技術面 / 籌碼" },
  { label: "美股", value: "us", enabled: true, summary: "主檔 / 日線 / SEC" },
  { label: "日股", value: "jp", enabled: false, summary: "尚未啟用" },
  { label: "韓股", value: "kr", enabled: false, summary: "尚未啟用" },
  { label: "港股", value: "hk", enabled: false, summary: "尚未啟用" },
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

const PINNED_INDEX_GROUP_NAME = "加權指數";
const PINNED_INDEX_ITEMS = [
  { stockId: "TAIEX", stockName: "加權指數", note: "TWSE" },
  { stockId: "TPEX", stockName: "櫃買指數", note: "TPEx" },
];

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
  const option = getSidebarMarketOption(selectedMarket);

  return (
    <div className="flex min-h-0 flex-1 flex-col border-b border-slate-200 px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
        Market
      </div>
      <div className="mt-1 text-lg font-bold text-slate-950">{option.label}</div>
      <div className="mt-2 border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
        {option.summary}
      </div>
      {!option.enabled ? (
        <div className="mt-3 border border-slate-200 bg-white px-3 py-3 text-xs text-slate-500">
          目前先保留市場入口。
        </div>
      ) : null}
    </div>
  );
}

export default function SidebarWatchlistExplorer({
  initialTree,
  initialItems,
  selectedGroupId,
  selectedStockId,
  selectedMarket,
  onSelectGroup,
  onSelectStock,
  onMarketChange,
  onExplorerDataChanged,
  onChanged,
}: Props) {
  const [tree, setTree] = useState<WatchlistGroupNode[]>(initialTree);
  const [items, setItems] = useState<WatchlistItemRead[]>(initialItems);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [indexGroupExpanded, setIndexGroupExpanded] = useState(true);
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
      onSelectGroup(currentGroup);
      setRenameValue(currentGroup?.group_name ?? "");
      setExpandedIds((previous) => {
        if (selectedGroupId === null) return previous;

        const next = new Set(previous);
        next.add(selectedGroupId);
        return next;
      });
      return currentGroup;
    }

    onSelectGroup(null);
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
      setMessage({ type: "success", text: "已重讀自選股清單" });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "自選股清單重讀失敗",
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
      setExpandedIds(new Set());
    }, 0);

    return () => window.clearTimeout(timer);
  }, [initialTree, initialItems]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      reloadExplorerData({ keepSelection: selectedGroupId !== null }).catch((error) => {
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
      return allGroups.find((group) => group.id === payload.groupId)?.group_name ?? "分組";
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
        "已移動分組",
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
      "已移動股票",
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
      "已調整股票順序",
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
      "已移到根層",
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

  function renderPinnedIndexGroup() {
    const selected = PINNED_INDEX_ITEMS.some((item) => item.stockId === selectedStockId);

    return (
      <div>
        <div
          className={[
            "relative flex cursor-pointer items-center gap-1 py-1 pr-1 text-sm",
            selected ? "bg-red-700 text-white" : "text-slate-700 hover:bg-slate-100",
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
              selected ? "text-white" : "text-slate-500",
            ].join(" ")}
            aria-label="切換加權指數資料夾"
          >
            {indexGroupExpanded ? "v" : ">"}
          </button>

          <div className="min-w-0 flex-1 text-left">
            <div className="truncate font-semibold">{PINNED_INDEX_GROUP_NAME}</div>
          </div>

          <span className={selected ? "pr-2 text-xs text-red-100" : "pr-2 text-xs text-slate-400"}>
            {PINNED_INDEX_ITEMS.length}
          </span>
        </div>

        {indexGroupExpanded ? (
          <div>
            {PINNED_INDEX_ITEMS.map((item) => {
              const itemSelected = item.stockId === selectedStockId;

              return (
                <button
                  key={item.stockId}
                  type="button"
                  className={[
                    "group relative flex w-full cursor-pointer items-center gap-1 py-1.5 pr-2 text-left text-xs",
                    itemSelected
                      ? "bg-slate-900 text-white"
                      : "text-slate-700 hover:bg-slate-100",
                  ].join(" ")}
                  style={{ paddingLeft: "24px" }}
                  onMouseDown={(event) => {
                    if (event.button !== 0) return;
                    onSelectStock(item.stockId, item.stockName);
                  }}
                  onClick={() => onSelectStock(item.stockId, item.stockName)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold">
                      {item.stockId} {item.stockName}
                    </div>
                    <div className={itemSelected ? "truncate text-slate-300" : "truncate text-slate-400"}>
                      {item.note}
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
            groupDropInside ? "ring-1 ring-inset ring-red-600" : "",
            selected ? "bg-red-700 text-white" : "text-slate-700 hover:bg-slate-100",
          ].join(" ")}
          style={{ paddingLeft: `${6 + depth * 10}px` }}
          data-watchlist-group-id={node.id}
          onClick={() => selectGroup(node)}
        >
          {groupDropBefore ? (
            <div className="absolute left-0 right-0 top-0 h-0.5 bg-red-700" />
          ) : null}
          {groupDropAfter ? (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-red-700" />
          ) : null}
          <button
            type="button"
            aria-label="移動分組"
            onPointerDown={(event) =>
              beginPointerDrag(event, { type: "group", groupId: node.id })
            }
            onClick={(event) => event.stopPropagation()}
            className={[
              "h-6 w-3 select-none text-[9px] font-bold leading-none",
              selected ? "text-red-100" : "text-slate-400 hover:text-red-700",
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
              selected ? "text-white" : "text-slate-500",
              !hasContent ? "opacity-40" : "",
            ].join(" ")}
          >
            {hasContent ? (expanded ? "v" : ">") : "-"}
          </button>

          <div className="min-w-0 flex-1 text-left">
            <div className="truncate font-semibold">{node.group_name}</div>
          </div>

          <span className={selected ? "pr-2 text-xs text-red-100" : "pr-2 text-xs text-slate-400"}>
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
                      ? "bg-slate-900 text-white"
                      : item.enabled
                        ? "text-slate-700 hover:bg-slate-100"
                        : "text-slate-400",
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
                    <div className="absolute left-0 right-0 top-0 h-0.5 bg-red-700" />
                  ) : null}
                  <button
                    type="button"
                    aria-label="移動股票"
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
                      itemSelected ? "text-slate-300" : "text-slate-300 hover:text-red-700",
                    ].join(" ")}
                  >
                    ::
                  </button>
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
                      draggable={false}
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
                      draggable={false}
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
        <div className="mt-3 grid grid-cols-5 border border-slate-200 bg-slate-50 p-1">
          {sidebarMarketOptions.map((option) => (
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

      {selectedMarket === "tw" ? (
        <>
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
          onClick={() => void reloadSelectedGroupList()}
          disabled={loading || reloadingExplorerData}
        >
          {reloadingExplorerData ? "重讀中" : "重讀清單"}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {dragPayload?.type === "group" ? (
          <div
            className={[
              "mx-2 mb-2 border border-dashed px-3 py-2 text-center text-xs font-semibold",
              dragOverKey === "root"
                ? "border-red-700 bg-red-50 text-red-700"
                : "border-slate-300 text-slate-500",
            ].join(" ")}
            data-watchlist-root-drop="true"
          >
            移到最外層
          </div>
        ) : null}
        {renderPinnedIndexGroup()}
        {tree.length > 0 ? (
          tree.map((node) => renderGroupNode(node))
        ) : (
          <div className="px-4 py-6 text-sm text-slate-500">尚未建立分組</div>
        )}
      </div>

      {pointerDrag?.active ? (
        <div
          className="pointer-events-none fixed z-50 max-w-48 border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-800 shadow-sm"
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
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700",
          ].join(" ")}
        >
          {message.text}
        </div>
      ) : null}

      <div className="border-b border-slate-200 px-4 py-4">
        <JobStatusCenter placement="inline" market="tw" />
      </div>

      <div className="space-y-4 p-4">
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
        </>
      ) : (
        <SidebarMarketSummary selectedMarket={selectedMarket} />
      )}
    </aside>
  );
}

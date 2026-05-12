"use client";

import { useEffect, useMemo, useState } from "react";
import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type { WatchlistGroupRead, WatchlistItemRead } from "@/types/market";

type Props = {
  selectedGroupId: number | null;
  onChanged: () => Promise<void> | void;
};

type Message = {
  type: "success" | "error";
  text: string;
} | null;

function inputClass() {
  return "w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm outline-none focus:border-indigo-400";
}

function buttonClass(kind: "primary" | "secondary" | "danger" = "secondary") {
  if (kind === "primary") {
    return "rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700";
  }

  if (kind === "danger") {
    return "rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-rose-700";
  }

  return "rounded-xl bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-200";
}

export default function WatchlistManager({ selectedGroupId, onChanged }: Props) {
  const [groups, setGroups] = useState<WatchlistGroupRead[]>([]);
  const [items, setItems] = useState<WatchlistItemRead[]>([]);
  const [message, setMessage] = useState<Message>(null);
  const [loading, setLoading] = useState(false);

  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupDescription, setNewGroupDescription] = useState("");
  const [newGroupParentId, setNewGroupParentId] = useState<string>("");
  const [newGroupSortOrder, setNewGroupSortOrder] = useState("100");

  const [newItemGroupId, setNewItemGroupId] = useState<string>("");
  const [newItemStockId, setNewItemStockId] = useState("");
  const [newItemNote, setNewItemNote] = useState("");
  const [newItemPriority, setNewItemPriority] = useState("100");
  const [newItemTags, setNewItemTags] = useState("");

  const activeGroups = useMemo(
    () => groups.filter((group) => group.is_active),
    [groups]
  );

  async function reloadManagerData() {
    const [groupData, itemData] = await Promise.all([
      fetchJson<WatchlistGroupRead[]>("/api/watchlists/groups"),
      fetchJson<WatchlistItemRead[]>("/api/watchlists/items", {
        limit: 1000,
        offset: 0,
      }),
    ]);

    setGroups(groupData);
    setItems(itemData);

    if (!newGroupParentId && selectedGroupId !== null) {
      setNewGroupParentId(String(selectedGroupId));
    }

    if (!newItemGroupId && selectedGroupId !== null) {
      setNewItemGroupId(String(selectedGroupId));
    }
  }

  async function runAction(action: () => Promise<void>, successText: string) {
    setLoading(true);
    setMessage(null);

    try {
      await action();
      await reloadManagerData();
      await onChanged();
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
    reloadManagerData().catch((error) => {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to load manager data",
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedGroupId !== null) {
      setNewGroupParentId(String(selectedGroupId));
      setNewItemGroupId(String(selectedGroupId));
    }
  }, [selectedGroupId]);

  async function createGroup() {
    const groupName = newGroupName.trim();

    if (!groupName) {
      setMessage({ type: "error", text: "Group name is required." });
      return;
    }

    await runAction(async () => {
      await requestJson<WatchlistGroupRead>("/api/watchlists/groups", {
        method: "POST",
        body: JSON.stringify({
          parent_id: newGroupParentId ? Number(newGroupParentId) : null,
          group_name: groupName,
          description: newGroupDescription.trim() || null,
          sort_order: Number(newGroupSortOrder || 100),
          is_active: true,
        }),
      });

      setNewGroupName("");
      setNewGroupDescription("");
      setNewGroupSortOrder("100");
    }, "Group created.");
  }

  async function updateGroup(
    groupId: number,
    payload: Partial<{
      parent_id: number | null;
      group_name: string;
      description: string | null;
      sort_order: number;
      is_active: boolean;
    }>
  ) {
    await runAction(async () => {
      await requestJson<WatchlistGroupRead>(`/api/watchlists/groups/${groupId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    }, "Group updated.");
  }

  async function createItem() {
    const stockId = newItemStockId.trim();

    if (!newItemGroupId) {
      setMessage({ type: "error", text: "Group is required." });
      return;
    }

    if (!stockId) {
      setMessage({ type: "error", text: "Stock id is required." });
      return;
    }

    await runAction(async () => {
      await requestJson<WatchlistItemRead>("/api/watchlists/items", {
        method: "POST",
        body: JSON.stringify({
          group_id: Number(newItemGroupId),
          stock_id: stockId,
          note: newItemNote.trim() || null,
          priority: Number(newItemPriority || 100),
          tags: newItemTags.trim() || null,
          enabled: true,
        }),
      });

      setNewItemStockId("");
      setNewItemNote("");
      setNewItemPriority("100");
      setNewItemTags("");
    }, "Watchlist item created.");
  }

  async function updateItem(
    itemId: number,
    payload: Partial<{
      group_id: number;
      stock_id: string;
      note: string | null;
      priority: number;
      tags: string | null;
      enabled: boolean;
    }>
  ) {
    await runAction(async () => {
      await requestJson<WatchlistItemRead>(`/api/watchlists/items/${itemId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    }, "Watchlist item updated.");
  }

  async function deleteItem(itemId: number) {
    const confirmed = window.confirm("確定要刪除這筆自選股嗎？");

    if (!confirmed) return;

    await runAction(async () => {
      await deleteRequest(`/api/watchlists/items/${itemId}`);
    }, "Watchlist item deleted.");
  }

  return (
    <div className="space-y-5">
      <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold">Watchlist Management</h2>
            <p className="mt-1 text-sm text-slate-500">
              先做簡易管理介面，取代 Swagger 手動改 JSON。
            </p>
          </div>

          <button
            type="button"
            onClick={() => void reloadManagerData()}
            className={buttonClass("secondary")}
            disabled={loading}
          >
            Refresh
          </button>
        </div>

        {message ? (
          <div
            className={[
              "mt-4 rounded-2xl border p-4 text-sm",
              message.type === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-rose-200 bg-rose-50 text-rose-700",
            ].join(" ")}
          >
            {message.text}
          </div>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
          <h3 className="text-base font-bold">Create Group</h3>

          <div className="mt-4 grid gap-3">
            <input
              className={inputClass()}
              placeholder="Group name，例如：PCB / CCL"
              value={newGroupName}
              onChange={(event) => setNewGroupName(event.target.value)}
            />

            <input
              className={inputClass()}
              placeholder="Description"
              value={newGroupDescription}
              onChange={(event) => setNewGroupDescription(event.target.value)}
            />

            <select
              className={inputClass()}
              value={newGroupParentId}
              onChange={(event) => setNewGroupParentId(event.target.value)}
            >
              <option value="">No parent / Root</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  #{group.id} {group.group_name}
                  {!group.is_active ? " (inactive)" : ""}
                </option>
              ))}
            </select>

            <input
              className={inputClass()}
              placeholder="Sort order"
              type="number"
              value={newGroupSortOrder}
              onChange={(event) => setNewGroupSortOrder(event.target.value)}
            />

            <button
              type="button"
              onClick={() => void createGroup()}
              className={buttonClass("primary")}
              disabled={loading}
            >
              Create Group
            </button>
          </div>
        </div>

        <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
          <h3 className="text-base font-bold">Create Watchlist Item</h3>

          <div className="mt-4 grid gap-3">
            <select
              className={inputClass()}
              value={newItemGroupId}
              onChange={(event) => setNewItemGroupId(event.target.value)}
            >
              <option value="">Select group</option>
              {activeGroups.map((group) => (
                <option key={group.id} value={group.id}>
                  #{group.id} {group.group_name}
                </option>
              ))}
            </select>

            <input
              className={inputClass()}
              placeholder="Stock id，例如：2330"
              value={newItemStockId}
              onChange={(event) => setNewItemStockId(event.target.value)}
            />

            <input
              className={inputClass()}
              placeholder="Note"
              value={newItemNote}
              onChange={(event) => setNewItemNote(event.target.value)}
            />

            <input
              className={inputClass()}
              placeholder="Priority"
              type="number"
              value={newItemPriority}
              onChange={(event) => setNewItemPriority(event.target.value)}
            />

            <input
              className={inputClass()}
              placeholder="Tags，例如：ETF,core"
              value={newItemTags}
              onChange={(event) => setNewItemTags(event.target.value)}
            />

            <button
              type="button"
              onClick={() => void createItem()}
              className={buttonClass("primary")}
              disabled={loading}
            >
              Add Stock
            </button>
          </div>
        </div>
      </div>

      <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
        <h3 className="text-base font-bold">Groups</h3>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Parent</th>
                <th className="px-4 py-3">Sort</th>
                <th className="px-4 py-3">Active</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {groups.map((group) => (
                <tr key={group.id}>
                  <td className="px-4 py-3 text-slate-500">#{group.id}</td>
                  <td className="px-4 py-3">
                    <input
                      className={inputClass()}
                      defaultValue={group.group_name}
                      onBlur={(event) => {
                        const value = event.target.value.trim();
                        if (value && value !== group.group_name) {
                          void updateGroup(group.id, { group_name: value });
                        }
                      }}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className={inputClass()}
                      value={group.parent_id ?? ""}
                      onChange={(event) =>
                        void updateGroup(group.id, {
                          parent_id: event.target.value
                            ? Number(event.target.value)
                            : null,
                        })
                      }
                    >
                      <option value="">Root</option>
                      {groups
                        .filter((candidate) => candidate.id !== group.id)
                        .map((candidate) => (
                          <option key={candidate.id} value={candidate.id}>
                            #{candidate.id} {candidate.group_name}
                          </option>
                        ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <input
                      className={inputClass()}
                      type="number"
                      defaultValue={group.sort_order}
                      onBlur={(event) => {
                        const value = Number(event.target.value || 100);
                        if (value !== group.sort_order) {
                          void updateGroup(group.id, { sort_order: value });
                        }
                      }}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={[
                        "rounded-full px-2.5 py-1 text-xs font-semibold ring-1",
                        group.is_active
                          ? "bg-emerald-100 text-emerald-700 ring-emerald-200"
                          : "bg-slate-100 text-slate-500 ring-slate-200",
                      ].join(" ")}
                    >
                      {group.is_active ? "active" : "inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() =>
                        void updateGroup(group.id, {
                          is_active: !group.is_active,
                        })
                      }
                      className={buttonClass("secondary")}
                      disabled={loading}
                    >
                      {group.is_active ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-3xl border border-white/70 bg-white/80 p-6 shadow-sm backdrop-blur">
        <h3 className="text-base font-bold">Watchlist Items</h3>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[1100px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Group</th>
                <th className="px-4 py-3">Stock</th>
                <th className="px-4 py-3">Note</th>
                <th className="px-4 py-3">Priority</th>
                <th className="px-4 py-3">Tags</th>
                <th className="px-4 py-3">Enabled</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="px-4 py-3 text-slate-500">#{item.id}</td>
                  <td className="px-4 py-3">
                    <select
                      className={inputClass()}
                      value={item.group_id}
                      onChange={(event) =>
                        void updateItem(item.id, {
                          group_id: Number(event.target.value),
                        })
                      }
                    >
                      {activeGroups.map((group) => (
                        <option key={group.id} value={group.id}>
                          #{group.id} {group.group_name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-semibold">{item.stock_id}</div>
                    <div className="text-xs text-slate-500">
                      {item.stock_name ?? "-"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <input
                      className={inputClass()}
                      defaultValue={item.note ?? ""}
                      onBlur={(event) =>
                        void updateItem(item.id, {
                          note: event.target.value.trim() || null,
                        })
                      }
                    />
                  </td>
                  <td className="px-4 py-3">
                    <input
                      className={inputClass()}
                      type="number"
                      defaultValue={item.priority}
                      onBlur={(event) =>
                        void updateItem(item.id, {
                          priority: Number(event.target.value || 100),
                        })
                      }
                    />
                  </td>
                  <td className="px-4 py-3">
                    <input
                      className={inputClass()}
                      defaultValue={item.tags ?? ""}
                      onBlur={(event) =>
                        void updateItem(item.id, {
                          tags: event.target.value.trim() || null,
                        })
                      }
                    />
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={[
                        "rounded-full px-2.5 py-1 text-xs font-semibold ring-1",
                        item.enabled
                          ? "bg-emerald-100 text-emerald-700 ring-emerald-200"
                          : "bg-slate-100 text-slate-500 ring-slate-200",
                      ].join(" ")}
                    >
                      {item.enabled ? "enabled" : "disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          void updateItem(item.id, {
                            enabled: !item.enabled,
                          })
                        }
                        className={buttonClass("secondary")}
                        disabled={loading}
                      >
                        {item.enabled ? "Disable" : "Enable"}
                      </button>

                      <button
                        type="button"
                        onClick={() => void deleteItem(item.id)}
                        className={buttonClass("danger")}
                        disabled={loading}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {items.length === 0 ? (
                <tr>
                  <td className="px-4 py-10 text-center text-slate-400" colSpan={8}>
                    No watchlist items.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
import { NextRequest, NextResponse } from "next/server";

import {
  backendConnectionIssueCode,
  fetchServerBackendJson,
} from "@/lib/serverBackend";
import type { BackendConnectionIssueCode } from "@/types/runtime";

function redirectHome(
  request: NextRequest,
  groupId?: string | number | null,
  errorCode?: BackendConnectionIssueCode | null
) {
  const url = new URL("/", request.url);

  if (groupId !== undefined && groupId !== null && String(groupId) !== "") {
    url.searchParams.set("group_id", String(groupId));
  }
  if (errorCode) url.searchParams.set("omi_error", errorCode);

  return NextResponse.redirect(url, 303);
}

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const intent = String(formData.get("intent") ?? "");
  const groupId = String(formData.get("group_id") ?? "");
  const itemId = String(formData.get("item_id") ?? "");

  try {
    if (intent === "create" && groupId) {
      await fetchServerBackendJson("/api/watchlists/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          group_id: Number(groupId),
          stock_id: String(formData.get("stock_id") ?? "").trim().toUpperCase(),
          note: String(formData.get("note") ?? "").trim() || null,
          priority: 100,
          tags: String(formData.get("tags") ?? "").trim() || null,
          enabled: true,
        }),
      });

      return redirectHome(request, groupId);
    }

    if (intent === "toggle" && itemId) {
      await fetchServerBackendJson(`/api/watchlists/items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: String(formData.get("enabled") ?? "") === "true",
        }),
      });

      return redirectHome(request, groupId);
    }

    if (intent === "delete" && itemId) {
      await fetchServerBackendJson(`/api/watchlists/items/${itemId}`, {
        method: "DELETE",
      });

      return redirectHome(request, groupId);
    }
  } catch (error) {
    const errorCode = backendConnectionIssueCode(error);
    console.error(
      `[watchlist-item-form] intent=${intent} code=${errorCode}`,
      error instanceof Error ? error.message : error
    );
    return redirectHome(request, groupId, errorCode);
  }

  return redirectHome(request, groupId);
}

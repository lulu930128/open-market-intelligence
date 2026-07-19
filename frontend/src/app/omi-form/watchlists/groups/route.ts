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
  const parentId = String(formData.get("parent_id") ?? "");
  const groupName = String(formData.get("group_name") ?? "").trim();

  try {
    if (intent === "create_root" || intent === "create_child") {
      const created = await fetchServerBackendJson<{ id?: number }>(
        "/api/watchlists/groups",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            parent_id: intent === "create_child" && parentId ? Number(parentId) : null,
            group_name: groupName,
            description: null,
            sort_order: 100,
            is_active: true,
          }),
        }
      );

      return redirectHome(request, created?.id);
    }

    if (intent === "rename" && groupId) {
      await fetchServerBackendJson(`/api/watchlists/groups/${groupId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group_name: groupName }),
      });

      return redirectHome(request, groupId);
    }

    if (intent === "delete" && groupId) {
      await fetchServerBackendJson(`/api/watchlists/groups/${groupId}?recursive=true`, {
        method: "DELETE",
      });

      return redirectHome(request);
    }
  } catch (error) {
    const errorCode = backendConnectionIssueCode(error);
    console.error(
      `[watchlist-group-form] intent=${intent} code=${errorCode}`,
      error instanceof Error ? error.message : error
    );
    return redirectHome(request, groupId, errorCode);
  }

  return redirectHome(request, groupId);
}

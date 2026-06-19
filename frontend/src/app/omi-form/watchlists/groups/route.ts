import { NextRequest, NextResponse } from "next/server";

import { getApiProxyTarget } from "@/lib/serverApiConfig";

const apiProxyTarget = getApiProxyTarget();

function redirectHome(request: NextRequest, groupId?: string | number | null) {
  const url = new URL("/", request.url);

  if (groupId !== undefined && groupId !== null && String(groupId) !== "") {
    url.searchParams.set("group_id", String(groupId));
  }

  return NextResponse.redirect(url, 303);
}

async function backendJson(path: string, init: RequestInit) {
  const response = await fetch(`${apiProxyTarget}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  if (response.status === 204) return null;

  return response.json();
}

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const intent = String(formData.get("intent") ?? "");
  const groupId = String(formData.get("group_id") ?? "");
  const parentId = String(formData.get("parent_id") ?? "");
  const groupName = String(formData.get("group_name") ?? "").trim();

  try {
    if (intent === "create_root" || intent === "create_child") {
      const created = await backendJson("/api/watchlists/groups", {
        method: "POST",
        body: JSON.stringify({
          parent_id: intent === "create_child" && parentId ? Number(parentId) : null,
          group_name: groupName,
          description: null,
          sort_order: 100,
          is_active: true,
        }),
      });

      return redirectHome(request, created?.id);
    }

    if (intent === "rename" && groupId) {
      await backendJson(`/api/watchlists/groups/${groupId}`, {
        method: "PATCH",
        body: JSON.stringify({ group_name: groupName }),
      });

      return redirectHome(request, groupId);
    }

    if (intent === "delete" && groupId) {
      await backendJson(`/api/watchlists/groups/${groupId}?recursive=true`, {
        method: "DELETE",
      });

      return redirectHome(request);
    }
  } catch {
    return redirectHome(request, groupId);
  }

  return redirectHome(request, groupId);
}

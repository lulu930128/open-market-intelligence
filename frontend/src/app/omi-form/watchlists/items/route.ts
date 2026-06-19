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
  const itemId = String(formData.get("item_id") ?? "");

  try {
    if (intent === "create" && groupId) {
      await backendJson("/api/watchlists/items", {
        method: "POST",
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
      await backendJson(`/api/watchlists/items/${itemId}`, {
        method: "PATCH",
        body: JSON.stringify({
          enabled: String(formData.get("enabled") ?? "") === "true",
        }),
      });

      return redirectHome(request, groupId);
    }

    if (intent === "delete" && itemId) {
      await backendJson(`/api/watchlists/items/${itemId}`, {
        method: "DELETE",
      });

      return redirectHome(request, groupId);
    }
  } catch {
    return redirectHome(request, groupId);
  }

  return redirectHome(request, groupId);
}

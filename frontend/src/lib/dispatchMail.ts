import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type { JobRunRead } from "@/types/market";

export type DispatchTemplateKey = "market_overview" | "watchlist_brief";
export type DispatchScopeType = "market" | "watchlist";
export type DispatchMarket = "tw" | "us";
export type DispatchDeliveryStatus =
  | "queued"
  | "sending"
  | "success"
  | "error"
  | string;

export type DispatchRecipientGroupRead = {
  id: number;
  name: string;
  description: string | null;
  emails: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type DispatchRecipientGroupWrite = {
  name: string;
  description?: string | null;
  emails: string[];
  enabled?: boolean;
};

export type DispatchPreviewRequest = {
  template_key: DispatchTemplateKey;
  scope_type: DispatchScopeType;
  scope_id?: string | number | null;
};

export type DispatchSendRequest = DispatchPreviewRequest & {
  recipient_group_id: number;
};

export type DispatchPreviewRead = {
  template_key: DispatchTemplateKey;
  scope_type: DispatchScopeType;
  scope_id: string | null;
  subject: string;
  body_text: string;
  body_html: string;
  generated_at: string;
  as_of: string | null;
  warnings: string[];
  missing: string[];
  metadata: Record<string, unknown>;
};

export type DispatchDeliveryRead = {
  id: number;
  job_run_id: number | null;
  recipient_group_id: number | null;
  recipient_group_name: string | null;
  template_key: DispatchTemplateKey;
  scope_type: DispatchScopeType;
  scope_id: string | null;
  subject: string;
  status: DispatchDeliveryStatus;
  recipient_count: number;
  recipients: string[];
  body_text: string;
  body_html: string;
  preview: Record<string, unknown>;
  request: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
};

export type DispatchSendRead = {
  job: JobRunRead;
  delivery: DispatchDeliveryRead;
};

export type WatchlistGroupOption = {
  id: number;
  group_name: string;
  is_active: boolean;
};

export function listDispatchRecipientGroups() {
  return fetchJson<DispatchRecipientGroupRead[]>("/api/dispatch/recipient-groups");
}

export function createDispatchRecipientGroup(payload: DispatchRecipientGroupWrite) {
  return requestJson<DispatchRecipientGroupRead>("/api/dispatch/recipient-groups", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateDispatchRecipientGroup(
  groupId: number,
  payload: Partial<DispatchRecipientGroupWrite>
) {
  return requestJson<DispatchRecipientGroupRead>(
    `/api/dispatch/recipient-groups/${groupId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    }
  );
}

export function deleteDispatchRecipientGroup(groupId: number) {
  return deleteRequest(`/api/dispatch/recipient-groups/${groupId}`);
}

export function previewDispatch(payload: DispatchPreviewRequest) {
  return requestJson<DispatchPreviewRead>("/api/dispatch/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sendDispatch(payload: DispatchSendRequest) {
  return requestJson<DispatchSendRead>("/api/dispatch/send", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listDispatchDeliveries(limit = 20) {
  return fetchJson<DispatchDeliveryRead[]>("/api/dispatch/deliveries", { limit });
}

export function listTaiwanWatchlistGroups() {
  return fetchJson<WatchlistGroupOption[]>("/api/watchlists/groups", {
    is_active: true,
  });
}

export function listUsWatchlistGroups() {
  return fetchJson<WatchlistGroupOption[]>("/api/us-market/watchlists/groups", {
    is_active: true,
  });
}

export function listDispatchWatchlistGroups(market: DispatchMarket) {
  if (market === "us") {
    return listUsWatchlistGroups();
  }
  return listTaiwanWatchlistGroups();
}

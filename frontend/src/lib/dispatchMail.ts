import { deleteRequest, fetchJson, requestJson } from "@/lib/api";
import type { JobRunRead } from "@/types/market";

export type DispatchTemplateKey = "market_overview" | "watchlist_brief";
export type DispatchScopeType = "market" | "watchlist";
export type DispatchMarket = "tw" | "us";
export type DispatchContentDepth = "standard" | "deep";
export type DispatchRadarMode =
  | "action"
  | "momentum"
  | "risk"
  | "breakout"
  | "surge"
  | "overheat"
  | "all";
export type DispatchDeliveryStatus =
  | "queued"
  | "sending"
  | "success"
  | "unknown"
  | "error"
  | string;
export type DispatchCalendarMode = "calendar_days" | "weekdays" | "tw_trading_days";
export type DispatchCatchupMode = "latest_only" | "all_slots";
export type DispatchMisfirePolicy = "catch_up" | "skip";
export type DispatchReadinessProfile =
  | "generic"
  | "tw_preopen"
  | "tw_post_close"
  | "watchlist_radar";
export type DispatchReadinessPolicy =
  | "immediate"
  | "wait_until_ready"
  | "skip_if_incomplete";

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
  strategy_profile?: string;
  rank_by?: string;
  sort_order?: string;
  include_radar?: boolean;
  radar_group_id?: number | null;
  radar_mode?: DispatchRadarMode;
  content_depth?: DispatchContentDepth;
  radar_limit?: number;
};

export type DispatchSendRequest = DispatchPreviewRequest & {
  recipient_group_id: number;
};

export type DispatchScheduleRead = {
  id: number;
  name: string;
  description: string | null;
  recipient_group_id: number | null;
  recipient_group_name: string | null;
  enabled: boolean;
  send_time: string;
  day_of_week: string;
  timezone: string;
  template_key: DispatchTemplateKey;
  scope_type: DispatchScopeType;
  scope_id: string | null;
  request: Partial<DispatchPreviewRequest>;
  next_run_at?: string | null;
  calendar_mode?: DispatchCalendarMode;
  catchup_mode?: DispatchCatchupMode;
  misfire_policy?: DispatchMisfirePolicy;
  misfire_grace_minutes?: number;
  max_retries?: number;
  retry_interval_seconds?: number;
  readiness_profile?: DispatchReadinessProfile;
  readiness_policy?: DispatchReadinessPolicy;
  readiness_deadline_minutes?: number;
  readiness_retry_interval_seconds?: number;
  last_queued_at?: string | null;
  last_sent_at?: string | null;
  last_skipped_at?: string | null;
  last_status?: string;
  archived_at?: string | null;
  last_run_key: string | null;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error_message: string | null;
  last_delivery_id: number | null;
  last_job_run_id: number | null;
  created_at: string;
  updated_at: string;
};

export type DispatchScheduleWrite = DispatchPreviewRequest & {
  name: string;
  description?: string | null;
  recipient_group_id: number;
  enabled?: boolean;
  send_time: string;
  day_of_week: string;
  timezone?: string;
  calendar_mode?: DispatchCalendarMode;
  catchup_mode?: DispatchCatchupMode;
  misfire_policy?: DispatchMisfirePolicy;
  misfire_grace_minutes?: number;
  max_retries?: number;
  retry_interval_seconds?: number;
  readiness_profile?: DispatchReadinessProfile;
  readiness_policy?: DispatchReadinessPolicy;
  readiness_deadline_minutes?: number;
  readiness_retry_interval_seconds?: number;
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
  message_id?: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
};

export type DispatchScheduleRunRead = {
  id: number;
  run_token: string;
  schedule_id: number;
  schedule_name: string | null;
  retry_of_run_id: number | null;
  trigger_type: "scheduled" | "manual" | "manual_retry" | string;
  scheduled_for: string;
  scheduled_slot_key: string | null;
  status: string;
  schedule_snapshot: Record<string, unknown>;
  readiness: Record<string, unknown> | null;
  readiness_check_count: number;
  delivery_attempt_count: number;
  max_delivery_attempts: number;
  next_action_at: string | null;
  retryable: boolean;
  error_code: string | null;
  error_message: string | null;
  delivery_id: number | null;
  job_run_id: number | null;
  claimed_at: string | null;
  queued_at: string | null;
  sending_at: string | null;
  sent_at: string | null;
  skipped_at: string | null;
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

export function listDispatchSchedules() {
  return fetchJson<DispatchScheduleRead[]>("/api/dispatch/schedules");
}

export function createDispatchSchedule(payload: DispatchScheduleWrite) {
  return requestJson<DispatchScheduleRead>("/api/dispatch/schedules", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateDispatchSchedule(
  scheduleId: number,
  payload: Partial<DispatchScheduleWrite>
) {
  return requestJson<DispatchScheduleRead>(`/api/dispatch/schedules/${scheduleId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteDispatchSchedule(scheduleId: number) {
  return deleteRequest(`/api/dispatch/schedules/${scheduleId}`);
}

export function runDispatchSchedule(scheduleId: number) {
  return requestJson<DispatchSendRead>(`/api/dispatch/schedules/${scheduleId}/run`, {
    method: "POST",
  });
}

export function listDispatchScheduleRuns(scheduleId: number, limit = 50) {
  return fetchJson<DispatchScheduleRunRead[]>(
    `/api/dispatch/schedules/${scheduleId}/runs`,
    { limit }
  );
}

export function createDispatchScheduleRun(scheduleId: number) {
  return requestJson<DispatchScheduleRunRead>(
    `/api/dispatch/schedules/${scheduleId}/runs`,
    { method: "POST" }
  );
}

export function retryDispatchScheduleRun(runId: number) {
  return requestJson<DispatchScheduleRunRead>(
    `/api/dispatch/schedule-runs/${runId}/retry`,
    { method: "POST" }
  );
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

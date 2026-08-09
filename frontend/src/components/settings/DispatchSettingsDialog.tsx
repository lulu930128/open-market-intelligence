"use client";

import { StateSurface } from "@/components/LoadingPlaceholders";
import { useT } from "@/i18n";
import {
  createDispatchSchedule,
  createDispatchRecipientGroup,
  deleteDispatchSchedule,
  deleteDispatchRecipientGroup,
  listDispatchDeliveries,
  listDispatchRecipientGroups,
  listDispatchScheduleRuns,
  listDispatchSchedules,
  listDispatchWatchlistGroups,
  previewDispatch,
  runDispatchSchedule,
  retryDispatchScheduleRun,
  sendDispatch,
  updateDispatchSchedule,
  updateDispatchRecipientGroup,
  type DispatchContentDepth,
  type DispatchCalendarMode,
  type DispatchCatchupMode,
  type DispatchDeliveryRead,
  type DispatchMarket,
  type DispatchPreviewRead,
  type DispatchPreviewRequest,
  type DispatchRadarMode,
  type DispatchReadinessPolicy,
  type DispatchReadinessProfile,
  type DispatchRecipientGroupRead,
  type DispatchScheduleRead,
  type DispatchScheduleRunRead,
  type DispatchScheduleWrite,
  type DispatchTemplateKey,
  type WatchlistGroupOption,
} from "@/lib/dispatchMail";
import { useCallback, useEffect, useMemo, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type ActionState = "idle" | "loading" | "error";
type PreviewMode = "html" | "text";

const DISPATCH_RADAR_MODES: DispatchRadarMode[] = [
  "action",
  "momentum",
  "risk",
  "breakout",
  "surge",
  "overheat",
  "all",
];

const DISPATCH_RADAR_LIMITS = [6, 8, 12, 16, 24] as const;

type Message = {
  type: "success" | "error";
  text: string;
} | null;

type DispatchSettingsDialogProps = {
  open: boolean;
  onClose: () => void;
};

function splitEmails(value: string) {
  return value
    .split(/[\n,;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatDateTime(value: string | null) {
  if (!value) return "-";

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;

  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function deliveryStatusClassName(status: DispatchDeliveryRead["status"]) {
  if (status === "success") return "text-omi-success";
  if (status === "error" || status === "unknown") return "text-omi-danger";
  if (status === "sending" || status === "queued") return "text-omi-accent";
  return "text-omi-text-muted";
}

function scheduleStatusClassName(schedule: DispatchScheduleRead) {
  if (!schedule.enabled) return "text-omi-text-muted";
  if (schedule.last_status === "error" || schedule.last_error_at) return "text-omi-danger";
  if (schedule.last_status === "success" || schedule.last_sent_at) return "text-omi-success";
  return "text-omi-accent";
}

function runStatusClassName(status: string) {
  if (status === "success") return "text-omi-success";
  if (status === "error" || status === "skipped") return "text-omi-danger";
  if (["claimed", "waiting_data", "queued", "sending", "retry_wait"].includes(status)) {
    return "text-omi-accent";
  }
  return "text-omi-text-muted";
}

function numberOrNull(value: unknown) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) && numberValue > 0 ? numberValue : null;
}

function toTextAreaValue(emails: string[]) {
  return emails.join("\n");
}

function readinessReason(run: DispatchScheduleRunRead) {
  const value = run.readiness?.reason_message;
  return typeof value === "string" && value.trim() ? value : null;
}

export default function DispatchSettingsDialog({
  open,
  onClose,
}: DispatchSettingsDialogProps) {
  const t = useT();
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [message, setMessage] = useState<Message>(null);
  const [recipientGroups, setRecipientGroups] = useState<DispatchRecipientGroupRead[]>(
    []
  );
  const [watchlistGroups, setWatchlistGroups] = useState<WatchlistGroupOption[]>([]);
  const [deliveries, setDeliveries] = useState<DispatchDeliveryRead[]>([]);
  const [schedules, setSchedules] = useState<DispatchScheduleRead[]>([]);
  const [selectedRecipientGroupId, setSelectedRecipientGroupId] =
    useState<number | null>(null);
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [groupName, setGroupName] = useState("");
  const [groupDescription, setGroupDescription] = useState("");
  const [emailsText, setEmailsText] = useState("");
  const [market, setMarket] = useState<DispatchMarket>("tw");
  const [templateKey, setTemplateKey] =
    useState<DispatchTemplateKey>("market_overview");
  const [watchlistGroupId, setWatchlistGroupId] = useState<number | null>(null);
  const [includeOverviewRadar, setIncludeOverviewRadar] = useState(false);
  const [contentDepth, setContentDepth] =
    useState<DispatchContentDepth>("standard");
  const [radarMode, setRadarMode] = useState<DispatchRadarMode>("action");
  const [radarLimit, setRadarLimit] = useState<number>(8);
  const [preview, setPreview] = useState<DispatchPreviewRead | null>(null);
  const [previewMode, setPreviewMode] = useState<PreviewMode>("html");
  const [savingGroup, setSavingGroup] = useState(false);
  const [deletingGroup, setDeletingGroup] = useState(false);
  const [sending, setSending] = useState(false);
  const [editingScheduleId, setEditingScheduleId] = useState<number | null>(null);
  const [scheduleName, setScheduleName] = useState("");
  const [scheduleDescription, setScheduleDescription] = useState("");
  const [scheduleTime, setScheduleTime] = useState("08:55");
  const [scheduleDayOfWeek, setScheduleDayOfWeek] = useState("mon-fri");
  const [scheduleEnabled, setScheduleEnabled] = useState(true);
  const [scheduleCalendarMode, setScheduleCalendarMode] =
    useState<DispatchCalendarMode>("weekdays");
  const [scheduleCatchupMode, setScheduleCatchupMode] =
    useState<DispatchCatchupMode>("latest_only");
  const [scheduleMisfirePolicy, setScheduleMisfirePolicy] =
    useState<"catch_up" | "skip">("catch_up");
  const [scheduleMisfireGraceMinutes, setScheduleMisfireGraceMinutes] = useState(15);
  const [scheduleMaxRetries, setScheduleMaxRetries] = useState(2);
  const [scheduleRetryIntervalSeconds, setScheduleRetryIntervalSeconds] = useState(300);
  const [scheduleReadinessProfile, setScheduleReadinessProfile] =
    useState<DispatchReadinessProfile>("generic");
  const [scheduleReadinessPolicy, setScheduleReadinessPolicy] =
    useState<DispatchReadinessPolicy>("immediate");
  const [scheduleReadinessDeadlineMinutes, setScheduleReadinessDeadlineMinutes] =
    useState(60);
  const [scheduleReadinessRetrySeconds, setScheduleReadinessRetrySeconds] =
    useState(300);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [deletingScheduleId, setDeletingScheduleId] = useState<number | null>(null);
  const [runningScheduleId, setRunningScheduleId] = useState<number | null>(null);
  const [scheduleRuns, setScheduleRuns] = useState<DispatchScheduleRunRead[]>([]);
  const [scheduleRunsState, setScheduleRunsState] = useState<LoadState>("idle");
  const [retryingRunId, setRetryingRunId] = useState<number | null>(null);

  const selectedRecipientGroup = useMemo(
    () =>
      recipientGroups.find((group) => group.id === selectedRecipientGroupId) ?? null,
    [recipientGroups, selectedRecipientGroupId]
  );

  const activeWatchlistGroups = useMemo(
    () => watchlistGroups.filter((group) => group.is_active),
    [watchlistGroups]
  );

  const showRadarControls =
    market === "tw" &&
    (templateKey === "watchlist_brief" ||
      (templateKey === "market_overview" && includeOverviewRadar));

  const loadData = useCallback(async () => {
    await Promise.resolve();
    setLoadState("loading");
    setActionState("idle");
    setMessage(null);

    try {
      const [
        nextRecipientGroups,
        nextDeliveries,
        nextWatchlistGroups,
        nextSchedules,
      ] =
        await Promise.all([
          listDispatchRecipientGroups(),
          listDispatchDeliveries(20),
          listDispatchWatchlistGroups(market),
          listDispatchSchedules(),
        ]);

      setRecipientGroups(nextRecipientGroups);
      setDeliveries(nextDeliveries);
      setWatchlistGroups(nextWatchlistGroups);
      setSchedules(nextSchedules);
      setSelectedRecipientGroupId(
        (current) => current ?? nextRecipientGroups[0]?.id ?? null
      );
      setWatchlistGroupId((current) =>
        nextWatchlistGroups.some((group) => group.id === current)
          ? current
          : nextWatchlistGroups[0]?.id ?? null
      );
      setLoadState("success");
    } catch (error) {
      setLoadState("error");
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.dispatch.loadError"),
      });
    }
  }, [market, t]);

  useEffect(() => {
    if (!open) return;
    const timerId = window.setTimeout(() => {
      void loadData();
    }, 0);
    return () => window.clearTimeout(timerId);
  }, [loadData, open]);

  function resetGroupForm() {
    setEditingGroupId(null);
    setGroupName("");
    setGroupDescription("");
    setEmailsText("");
    setMessage(null);
  }

  function editRecipientGroup(group: DispatchRecipientGroupRead) {
    setSelectedRecipientGroupId(group.id);
    setEditingGroupId(group.id);
    setGroupName(group.name);
    setGroupDescription(group.description ?? "");
    setEmailsText(toTextAreaValue(group.emails));
    setMessage(null);
  }

  function resetScheduleForm() {
    setEditingScheduleId(null);
    setScheduleName("");
    setScheduleDescription("");
    setScheduleTime("08:55");
    setScheduleDayOfWeek("mon-fri");
    setScheduleEnabled(true);
    setScheduleCalendarMode("weekdays");
    setScheduleCatchupMode("latest_only");
    setScheduleMisfirePolicy("catch_up");
    setScheduleMisfireGraceMinutes(15);
    setScheduleMaxRetries(2);
    setScheduleRetryIntervalSeconds(300);
    setScheduleReadinessProfile("generic");
    setScheduleReadinessPolicy("immediate");
    setScheduleReadinessDeadlineMinutes(60);
    setScheduleReadinessRetrySeconds(300);
    setScheduleRuns([]);
    setScheduleRunsState("idle");
    setMessage(null);
  }

  async function refreshScheduleRuns(scheduleId: number) {
    setScheduleRunsState("loading");
    try {
      setScheduleRuns(await listDispatchScheduleRuns(scheduleId, 30));
      setScheduleRunsState("success");
    } catch (error) {
      setScheduleRunsState("error");
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.dispatch.loadError"),
      });
    }
  }

  function editSchedule(schedule: DispatchScheduleRead) {
    const request = schedule.request ?? {};
    const scopeId = request.scope_id ?? schedule.scope_id;

    setEditingScheduleId(schedule.id);
    setScheduleName(schedule.name);
    setScheduleDescription(schedule.description ?? "");
    setScheduleTime(schedule.send_time);
    setScheduleDayOfWeek(schedule.day_of_week);
    setScheduleEnabled(schedule.enabled);
    setScheduleCalendarMode(schedule.calendar_mode ?? "weekdays");
    setScheduleCatchupMode(schedule.catchup_mode ?? "latest_only");
    setScheduleMisfirePolicy(schedule.misfire_policy ?? "catch_up");
    setScheduleMisfireGraceMinutes(schedule.misfire_grace_minutes ?? 15);
    setScheduleMaxRetries(schedule.max_retries ?? 2);
    setScheduleRetryIntervalSeconds(schedule.retry_interval_seconds ?? 300);
    setScheduleReadinessProfile(schedule.readiness_profile ?? "generic");
    setScheduleReadinessPolicy(schedule.readiness_policy ?? "immediate");
    setScheduleReadinessDeadlineMinutes(schedule.readiness_deadline_minutes ?? 60);
    setScheduleReadinessRetrySeconds(
      schedule.readiness_retry_interval_seconds ?? 300
    );
    setSelectedRecipientGroupId(schedule.recipient_group_id);
    setTemplateKey(schedule.template_key);
    setContentDepth(request.content_depth ?? "standard");
    setRadarMode(request.radar_mode ?? "action");
    setRadarLimit(Number(request.radar_limit ?? 8));

    if (schedule.template_key === "watchlist_brief") {
      setMarket("tw");
      setIncludeOverviewRadar(false);
      setWatchlistGroupId(numberOrNull(scopeId));
    } else {
      const nextMarket = scopeId === "us" ? "us" : "tw";
      const radarGroupId = numberOrNull(request.radar_group_id);
      setMarket(nextMarket);
      setIncludeOverviewRadar(nextMarket === "tw" && Boolean(request.include_radar));
      setWatchlistGroupId(nextMarket === "tw" ? radarGroupId : null);
    }

    setPreview(null);
    setMessage(null);
    void refreshScheduleRuns(schedule.id);
  }

  function buildPreviewRequest(): DispatchPreviewRequest | null {
    if (templateKey === "watchlist_brief") {
      if (market !== "tw") {
        setMessage({
          type: "error",
          text: t("settings.dispatch.validationUnsupportedMarketTemplate"),
        });
        return null;
      }

      if (!watchlistGroupId) {
        setMessage({
          type: "error",
          text: t("settings.dispatch.validationWatchlistGroup"),
        });
        return null;
      }

      return {
        template_key: "watchlist_brief",
        scope_type: "watchlist",
        scope_id: String(watchlistGroupId),
        strategy_profile: "short_term_momentum",
        rank_by: "score",
        sort_order: "desc",
        radar_mode: radarMode,
        content_depth: contentDepth,
        radar_limit: radarLimit,
      };
    }

    if (market === "tw" && includeOverviewRadar && !watchlistGroupId) {
      setMessage({
        type: "error",
        text: t("settings.dispatch.validationWatchlistGroup"),
      });
      return null;
    }

    return {
      template_key: "market_overview",
      scope_type: "market",
      scope_id: market,
      include_radar: market === "tw" ? includeOverviewRadar : false,
      radar_group_id:
        market === "tw" && includeOverviewRadar ? watchlistGroupId : null,
      strategy_profile: "short_term_momentum",
      rank_by: "score",
      sort_order: "desc",
      radar_mode: radarMode,
      content_depth: contentDepth,
      radar_limit: radarLimit,
    };
  }

  function buildSchedulePayload(): DispatchScheduleWrite | null {
    const name = scheduleName.trim();
    if (!name) {
      setMessage({
        type: "error",
        text: t("settings.dispatch.validationScheduleName"),
      });
      return null;
    }

    if (!scheduleTime.trim()) {
      setMessage({
        type: "error",
        text: t("settings.dispatch.validationScheduleTime"),
      });
      return null;
    }

    if (!selectedRecipientGroupId) {
      setMessage({
        type: "error",
        text: t("settings.dispatch.validationRecipientGroup"),
      });
      return null;
    }

    const request = buildPreviewRequest();
    if (!request) return null;

    return {
      ...request,
      name,
      description: scheduleDescription.trim() || null,
      recipient_group_id: selectedRecipientGroupId,
      enabled: scheduleEnabled,
      send_time: scheduleTime.trim(),
      day_of_week: scheduleDayOfWeek.trim() || "mon-fri",
      timezone: "Asia/Taipei",
      calendar_mode: scheduleCalendarMode,
      catchup_mode: scheduleCatchupMode,
      misfire_policy: scheduleMisfirePolicy,
      misfire_grace_minutes: scheduleMisfireGraceMinutes,
      max_retries: scheduleMaxRetries,
      retry_interval_seconds: scheduleRetryIntervalSeconds,
      readiness_profile: scheduleReadinessProfile,
      readiness_policy: scheduleReadinessPolicy,
      readiness_deadline_minutes: scheduleReadinessDeadlineMinutes,
      readiness_retry_interval_seconds: scheduleReadinessRetrySeconds,
    };
  }

  async function saveRecipientGroup() {
    const name = groupName.trim();
    const emails = splitEmails(emailsText);

    if (!name) {
      setMessage({ type: "error", text: t("settings.dispatch.validationName") });
      return;
    }

    if (emails.length === 0) {
      setMessage({ type: "error", text: t("settings.dispatch.validationEmails") });
      return;
    }

    setSavingGroup(true);
    setMessage(null);

    try {
      const payload = {
        name,
        description: groupDescription.trim() || null,
        emails,
        enabled: true,
      };
      const savedGroup = editingGroupId
        ? await updateDispatchRecipientGroup(editingGroupId, payload)
        : await createDispatchRecipientGroup(payload);

      setRecipientGroups((current) => {
        const exists = current.some((group) => group.id === savedGroup.id);
        if (!exists) return [savedGroup, ...current];
        return current.map((group) => (group.id === savedGroup.id ? savedGroup : group));
      });
      setSelectedRecipientGroupId(savedGroup.id);
      setEditingGroupId(savedGroup.id);
      setGroupName(savedGroup.name);
      setGroupDescription(savedGroup.description ?? "");
      setEmailsText(toTextAreaValue(savedGroup.emails));
      setMessage({ type: "success", text: t("settings.dispatch.groupSaved") });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.saveError"),
      });
    } finally {
      setSavingGroup(false);
    }
  }

  async function deleteRecipientGroup() {
    if (!editingGroupId) return;
    if (!window.confirm(t("settings.dispatch.confirmDeleteGroup"))) return;

    setDeletingGroup(true);
    setMessage(null);

    try {
      await deleteDispatchRecipientGroup(editingGroupId);
      setRecipientGroups((current) =>
        current.filter((group) => group.id !== editingGroupId)
      );
      setSelectedRecipientGroupId((current) =>
        current === editingGroupId ? null : current
      );
      resetGroupForm();
      setMessage({ type: "success", text: t("settings.dispatch.groupDeleted") });
      setDeliveries(await listDispatchDeliveries(20));
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.saveError"),
      });
    } finally {
      setDeletingGroup(false);
    }
  }

  async function buildPreview() {
    const request = buildPreviewRequest();
    if (!request) return;

    setActionState("loading");
    setMessage(null);

    try {
      const nextPreview = await previewDispatch(request);
      setPreview(nextPreview);
      setPreviewMode("html");
      setActionState("idle");
      setMessage({ type: "success", text: t("settings.dispatch.previewReady") });
    } catch (error) {
      setActionState("error");
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.dispatch.previewError"),
      });
    }
  }

  async function sendReport() {
    const request = buildPreviewRequest();
    if (!request) return;

    if (!selectedRecipientGroupId) {
      setMessage({
        type: "error",
        text: t("settings.dispatch.validationRecipientGroup"),
      });
      return;
    }

    setSending(true);
    setMessage(null);

    try {
      const result = await sendDispatch({
        ...request,
        recipient_group_id: selectedRecipientGroupId,
      });
      setDeliveries((current) => [result.delivery, ...current].slice(0, 20));
      setPreview({
        template_key: result.delivery.template_key,
        scope_type: result.delivery.scope_type,
        scope_id: result.delivery.scope_id,
        subject: result.delivery.subject,
        body_text: result.delivery.body_text,
        body_html: result.delivery.body_html,
        generated_at: result.delivery.created_at,
        as_of: null,
        warnings: [],
        missing: [],
        metadata: result.delivery.preview,
      });
      setPreviewMode("html");
      setMessage({
        type: "success",
        text: t("settings.dispatch.sendQueued", { jobId: result.job.id }),
      });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.dispatch.sendError"),
      });
    } finally {
      setSending(false);
    }
  }

  async function saveSchedule() {
    const payload = buildSchedulePayload();
    if (!payload) return;

    setSavingSchedule(true);
    setMessage(null);

    try {
      const savedSchedule = editingScheduleId
        ? await updateDispatchSchedule(editingScheduleId, payload)
        : await createDispatchSchedule(payload);

      setSchedules((current) => {
        const exists = current.some((schedule) => schedule.id === savedSchedule.id);
        if (!exists) return [savedSchedule, ...current];
        return current.map((schedule) =>
          schedule.id === savedSchedule.id ? savedSchedule : schedule
        );
      });
      setEditingScheduleId(savedSchedule.id);
      setScheduleName(savedSchedule.name);
      setScheduleDescription(savedSchedule.description ?? "");
      setScheduleTime(savedSchedule.send_time);
      setScheduleDayOfWeek(savedSchedule.day_of_week);
      setScheduleEnabled(savedSchedule.enabled);
      setScheduleCalendarMode(savedSchedule.calendar_mode ?? "weekdays");
      setScheduleCatchupMode(savedSchedule.catchup_mode ?? "latest_only");
      setScheduleMisfirePolicy(savedSchedule.misfire_policy ?? "catch_up");
      setScheduleMisfireGraceMinutes(savedSchedule.misfire_grace_minutes ?? 15);
      setScheduleMaxRetries(savedSchedule.max_retries ?? 2);
      setScheduleRetryIntervalSeconds(savedSchedule.retry_interval_seconds ?? 300);
      setScheduleReadinessProfile(savedSchedule.readiness_profile ?? "generic");
      setScheduleReadinessPolicy(savedSchedule.readiness_policy ?? "immediate");
      setScheduleReadinessDeadlineMinutes(
        savedSchedule.readiness_deadline_minutes ?? 60
      );
      setScheduleReadinessRetrySeconds(
        savedSchedule.readiness_retry_interval_seconds ?? 300
      );
      await refreshScheduleRuns(savedSchedule.id);
      setMessage({ type: "success", text: t("settings.dispatch.scheduleSaved") });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.saveError"),
      });
    } finally {
      setSavingSchedule(false);
    }
  }

  async function deleteSchedule() {
    if (!editingScheduleId) return;
    if (!window.confirm(t("settings.dispatch.confirmDeleteSchedule"))) return;

    setDeletingScheduleId(editingScheduleId);
    setMessage(null);

    try {
      await deleteDispatchSchedule(editingScheduleId);
      setSchedules((current) =>
        current.filter((schedule) => schedule.id !== editingScheduleId)
      );
      resetScheduleForm();
      setMessage({ type: "success", text: t("settings.dispatch.scheduleDeleted") });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.saveError"),
      });
    } finally {
      setDeletingScheduleId(null);
    }
  }

  async function runScheduleNow(scheduleId: number) {
    setRunningScheduleId(scheduleId);
    setMessage(null);

    try {
      const result = await runDispatchSchedule(scheduleId);
      setDeliveries((current) => [result.delivery, ...current].slice(0, 20));
      setSchedules(await listDispatchSchedules());
      await refreshScheduleRuns(scheduleId);
      setMessage({
        type: "success",
        text: t("settings.dispatch.scheduleRunQueued", { jobId: result.job.id }),
      });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.dispatch.sendError"),
      });
    } finally {
      setRunningScheduleId(null);
    }
  }

  async function toggleScheduleEnabled(schedule: DispatchScheduleRead) {
    setMessage(null);
    try {
      const updated = await updateDispatchSchedule(schedule.id, {
        enabled: !schedule.enabled,
      });
      setSchedules((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
      if (editingScheduleId === updated.id) {
        setScheduleEnabled(updated.enabled);
      }
      setMessage({
        type: "success",
        text: updated.enabled
          ? t("settings.dispatch.scheduleResumed")
          : t("settings.dispatch.schedulePaused"),
      });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.saveError"),
      });
    }
  }

  async function retryScheduleRun(runId: number) {
    if (!editingScheduleId) return;
    setRetryingRunId(runId);
    setMessage(null);
    try {
      await retryDispatchScheduleRun(runId);
      await Promise.all([
        refreshScheduleRuns(editingScheduleId),
        listDispatchDeliveries(20).then(setDeliveries),
      ]);
      setMessage({ type: "success", text: t("settings.dispatch.retryQueued") });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : t("settings.dispatch.sendError"),
      });
    } finally {
      setRetryingRunId(null);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[2147483646] flex items-center justify-center bg-omi-overlay p-4">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="dispatch-settings-title"
        className="flex h-[820px] max-h-[calc(100vh-2rem)] w-[1360px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden border border-omi-control-border bg-omi-surface shadow-2xl"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
          <div className="min-w-0">
            <div className="text-xs font-bold uppercase tracking-[0.22em] text-omi-accent">
              Settings
            </div>
            <h2
              id="dispatch-settings-title"
              className="mt-1 text-xl font-black text-omi-text-strong"
            >
              {t("settings.dispatch.title")}
            </h2>
            <p className="mt-1 text-sm leading-6 text-omi-text-muted">
              {t("settings.dispatch.hint")}
            </p>
          </div>
          <button
            type="button"
            aria-label={t("settings.dispatch.close")}
            className="grid h-8 w-8 shrink-0 place-items-center border border-omi-border text-omi-text-muted hover:border-omi-control hover:text-omi-text-strong"
            onClick={onClose}
          >
            <span aria-hidden="true" className="text-lg leading-none">
              x
            </span>
          </button>
        </header>

        {message ? (
          <div
            className={[
              "omi-feedback-strip shrink-0 border-b px-5 py-2 text-sm font-semibold",
              message.type === "error"
                ? "omi-feedback-strip-danger"
                : "omi-feedback-strip-success",
            ].join(" ")}
          >
            {message.text}
          </div>
        ) : null}

        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="min-h-0 overflow-y-auto border-b border-omi-border-subtle bg-omi-surface-subtle p-4 lg:border-b-0 lg:border-r">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-black text-omi-text-strong">
                  {t("settings.dispatch.recipientGroups")}
                </h3>
                <p className="mt-1 text-xs leading-5 text-omi-text-muted">
                  {t("settings.dispatch.recipientGroupsHint")}
                </p>
              </div>
              <button
                type="button"
                className="h-8 shrink-0 border border-omi-border bg-omi-surface px-3 text-xs font-bold text-omi-text-muted hover:border-omi-control"
                onClick={resetGroupForm}
              >
                {t("settings.dispatch.newGroup")}
              </button>
            </div>

            <div className="mt-4 grid gap-2">
              {loadState === "loading" ? (
                <div className="grid gap-2">
                  {Array.from({ length: 3 }).map((_, index) => (
                    <div key={index} className="omi-skeleton h-12 w-full" />
                  ))}
                </div>
              ) : recipientGroups.length === 0 ? (
                <StateSurface
                  title={t("settings.dispatch.noRecipientGroups")}
                  tone="empty"
                  compact
                />
              ) : (
                recipientGroups.map((group) => (
                  <button
                    key={group.id}
                    type="button"
                    className={[
                      "w-full border px-3 py-2 text-left transition",
                      selectedRecipientGroupId === group.id
                        ? "border-omi-accent bg-omi-control text-omi-text-inverse"
                        : "border-omi-border-subtle bg-omi-surface text-omi-text hover:border-omi-control",
                    ].join(" ")}
                    onClick={() => editRecipientGroup(group)}
                  >
                    <span className="block truncate text-sm font-bold">{group.name}</span>
                    <span
                      className={[
                        "mt-1 block truncate text-xs",
                        selectedRecipientGroupId === group.id
                          ? "text-omi-border"
                          : "text-omi-text-muted",
                      ].join(" ")}
                    >
                      {t("settings.dispatch.emailCount", {
                        count: group.emails.length,
                      })}
                    </span>
                  </button>
                ))
              )}
            </div>

            <div className="mt-5 border-t border-omi-border-subtle pt-4">
              <div className="grid gap-3">
                <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                  {t("settings.dispatch.groupName")}
                  <input
                    value={groupName}
                    onChange={(event) => setGroupName(event.target.value)}
                    className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                  />
                </label>
                <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                  {t("settings.dispatch.emails")}
                  <textarea
                    value={emailsText}
                    rows={5}
                    onChange={(event) => setEmailsText(event.target.value)}
                    placeholder={t("settings.dispatch.emailsHint")}
                    className="min-h-[112px] resize-y border border-omi-border bg-omi-surface px-3 py-2 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                  />
                </label>
                <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                  {t("settings.dispatch.description")}
                  <input
                    value={groupDescription}
                    onChange={(event) => setGroupDescription(event.target.value)}
                    className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                  />
                </label>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={savingGroup}
                  className="h-9 border border-omi-accent bg-omi-accent px-3 text-sm font-bold text-omi-text-inverse hover:bg-omi-control disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => void saveRecipientGroup()}
                >
                  {savingGroup
                    ? t("settings.saving")
                    : t("settings.dispatch.saveGroup")}
                </button>
                <button
                  type="button"
                  disabled={!editingGroupId || deletingGroup}
                  className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-bold text-omi-text-muted hover:border-omi-danger hover:text-omi-danger disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => void deleteRecipientGroup()}
                >
                  {t("settings.dispatch.deleteGroup")}
                </button>
              </div>
            </div>
          </aside>

          <main className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)]">
            <div className="border-b border-omi-border-subtle px-5 py-4">
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div>
                  <h3 className="text-sm font-black text-omi-text-strong">
                    {t("settings.dispatch.report")}
                  </h3>
                  <p className="mt-1 text-xs leading-5 text-omi-text-muted">
                    {t("settings.dispatch.reportHint")}
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                    {t("settings.dispatch.market")}
                    <select
                      value={market}
                      onChange={(event) => {
                        const nextMarket = event.target.value as DispatchMarket;
                        setMarket(nextMarket);
                        if (nextMarket !== "tw" && templateKey === "watchlist_brief") {
                          setTemplateKey("market_overview");
                        }
                        if (nextMarket !== "tw") {
                          setIncludeOverviewRadar(false);
                        }
                        setWatchlistGroupId(null);
                        setPreview(null);
                        setMessage(null);
                      }}
                      className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                    >
                      <option value="tw">{t("settings.dispatch.markets.tw")}</option>
                      <option value="us">{t("settings.dispatch.markets.us")}</option>
                    </select>
                  </label>
                  <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                    {t("settings.dispatch.template")}
                    <select
                      value={templateKey}
                      onChange={(event) => {
                        setTemplateKey(event.target.value as DispatchTemplateKey);
                        setIncludeOverviewRadar(false);
                        setPreview(null);
                      }}
                      className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                    >
                      <option value="market_overview">
                        {t("settings.dispatch.templates.market_overview")}
                      </option>
                      <option value="watchlist_brief" disabled={market !== "tw"}>
                        {t("settings.dispatch.templates.watchlist_brief")}
                      </option>
                    </select>
                  </label>
                  <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                    {t("settings.dispatch.recipientGroup")}
                    <select
                      value={selectedRecipientGroupId ?? ""}
                      onChange={(event) =>
                        setSelectedRecipientGroupId(
                          event.target.value ? Number(event.target.value) : null
                        )
                      }
                      className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                    >
                      <option value="">{t("settings.dispatch.noRecipientGroups")}</option>
                      {recipientGroups.map((group) => (
                        <option key={group.id} value={group.id}>
                          {group.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {templateKey === "market_overview" && market === "tw" ? (
                    <label className="flex min-h-9 items-center gap-2 border border-omi-border bg-omi-surface px-3 text-xs font-bold text-omi-text-muted sm:col-span-3">
                      <input
                        type="checkbox"
                        checked={includeOverviewRadar}
                        onChange={(event) => {
                          setIncludeOverviewRadar(event.target.checked);
                          setPreview(null);
                        }}
                        className="h-4 w-4 accent-omi-accent"
                      />
                      {t("settings.dispatch.overviewRadar")}
                    </label>
                  ) : null}
                  {showRadarControls ? (
                    <>
                      <label className="grid gap-1 text-xs font-bold text-omi-text-muted sm:col-span-3">
                        {t("settings.dispatch.watchlistGroup")}
                        <select
                          value={watchlistGroupId ?? ""}
                          onChange={(event) =>
                            setWatchlistGroupId(
                              event.target.value ? Number(event.target.value) : null
                            )
                          }
                          className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                        >
                          <option value="">
                            {t("settings.dispatch.validationWatchlistGroup")}
                          </option>
                          {activeWatchlistGroups.map((group) => (
                            <option key={group.id} value={group.id}>
                              {group.group_name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                        {t("settings.dispatch.contentDepth")}
                        <select
                          value={contentDepth}
                          onChange={(event) => {
                            const nextDepth = event.target.value as DispatchContentDepth;
                            setContentDepth(nextDepth);
                            if (nextDepth === "deep" && radarLimit < 12) {
                              setRadarLimit(16);
                            }
                            if (nextDepth === "standard" && radarLimit > 12) {
                              setRadarLimit(8);
                            }
                            setPreview(null);
                          }}
                          className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                        >
                          <option value="standard">
                            {t("settings.dispatch.contentDepthOptions.standard")}
                          </option>
                          <option value="deep">
                            {t("settings.dispatch.contentDepthOptions.deep")}
                          </option>
                        </select>
                      </label>
                      <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                        {t("settings.dispatch.radarMode")}
                        <select
                          value={radarMode}
                          onChange={(event) => {
                            setRadarMode(event.target.value as DispatchRadarMode);
                            setPreview(null);
                          }}
                          className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                        >
                          {DISPATCH_RADAR_MODES.map((mode) => (
                            <option key={mode} value={mode}>
                              {t(`settings.dispatch.radarModes.${mode}`)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="grid gap-1 text-xs font-bold text-omi-text-muted">
                        {t("settings.dispatch.radarLimit")}
                        <select
                          value={radarLimit}
                          onChange={(event) => {
                            setRadarLimit(Number(event.target.value));
                            setPreview(null);
                          }}
                          className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                        >
                          {DISPATCH_RADAR_LIMITS.map((limit) => (
                            <option key={limit} value={limit}>
                              {limit}
                            </option>
                          ))}
                        </select>
                      </label>
                    </>
                  ) : null}
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 text-xs text-omi-text-muted">
                  {selectedRecipientGroup
                    ? t("settings.dispatch.selectedRecipientSummary", {
                        name: selectedRecipientGroup.name,
                        count: selectedRecipientGroup.emails.length,
                      })
                    : t("settings.dispatch.validationRecipientGroup")}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-bold text-omi-text-muted hover:border-omi-control"
                    onClick={() => void buildPreview()}
                    disabled={actionState === "loading"}
                  >
                    {actionState === "loading"
                      ? t("settings.dispatch.previewing")
                      : t("settings.dispatch.preview")}
                  </button>
                  <button
                    type="button"
                    className="h-9 border border-omi-accent bg-omi-accent px-3 text-sm font-bold text-omi-text-inverse hover:bg-omi-control disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={sending || !selectedRecipientGroupId}
                    onClick={() => void sendReport()}
                  >
                    {sending ? t("settings.dispatch.sending") : t("settings.dispatch.send")}
                  </button>
                </div>
              </div>
            </div>

            <div className="grid min-h-0 grid-cols-1 xl:grid-cols-[minmax(0,1.3fr)_minmax(280px,0.7fr)]">
              <section className="min-h-0 overflow-y-auto border-b border-omi-border-subtle p-5 xl:border-b-0 xl:border-r">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-black text-omi-text-strong">
                    {t("settings.dispatch.preview")}
                  </h3>
                  <div className="flex min-w-0 items-center gap-2">
                    {preview ? (
                      <span className="truncate text-xs font-semibold text-omi-text-muted">
                        {preview.scope_type} / {preview.scope_id ?? "-"}
                      </span>
                    ) : null}
                    <div className="flex shrink-0 border border-omi-border-subtle">
                      {(["html", "text"] as const).map((mode) => (
                        <button
                          key={mode}
                          type="button"
                          className={[
                            "h-7 px-2 text-xs font-bold",
                            previewMode === mode
                              ? "bg-omi-control text-omi-text-inverse"
                              : "bg-omi-surface text-omi-text-muted hover:bg-omi-surface-subtle",
                          ].join(" ")}
                          onClick={() => setPreviewMode(mode)}
                          disabled={!preview}
                        >
                          {t(`settings.dispatch.previewMode.${mode}`)}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {preview ? (
                  <div className="mt-3">
                    <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
                      <div className="text-xs font-bold uppercase tracking-[0.14em] text-omi-text-muted">
                        {t("settings.dispatch.subject")}
                      </div>
                      <div className="mt-1 break-words text-sm font-bold text-omi-text-strong">
                        {preview.subject}
                      </div>
                    </div>
                    {previewMode === "html" ? (
                      <iframe
                        title={t("settings.dispatch.htmlPreviewTitle")}
                        sandbox=""
                        srcDoc={preview.body_html}
                        className="mt-3 h-[520px] w-full border border-omi-border-subtle bg-white"
                      />
                    ) : (
                      <pre className="mt-3 max-h-[440px] overflow-auto whitespace-pre-wrap border border-omi-border-subtle bg-omi-surface px-4 py-3 text-sm leading-6 text-omi-text">
                        {preview.body_text}
                      </pre>
                    )}
                  </div>
                ) : (
                  <StateSurface
                    title={t("settings.dispatch.emptyPreview")}
                    tone="empty"
                    className="mt-3 h-[260px]"
                  />
                )}
              </section>

              <section className="min-h-0 min-w-0 overflow-y-auto p-5">
                <div className="border-b border-omi-border-subtle pb-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="text-sm font-black text-omi-text-strong">
                        {t("settings.dispatch.schedules")}
                      </h3>
                      <p className="mt-1 text-xs leading-5 text-omi-text-muted">
                        {t("settings.dispatch.schedulesHint")}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="h-8 shrink-0 border border-omi-border bg-omi-surface px-3 text-xs font-bold text-omi-text-muted hover:border-omi-control"
                      onClick={resetScheduleForm}
                    >
                      {t("settings.dispatch.newSchedule")}
                    </button>
                  </div>

                  <div className="mt-4 grid min-w-0 gap-3">
                    <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                      {t("settings.dispatch.scheduleName")}
                      <input
                        value={scheduleName}
                        onChange={(event) => setScheduleName(event.target.value)}
                        className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                      />
                    </label>
                    <div className="grid min-w-0 gap-3 sm:grid-cols-[112px_minmax(0,1fr)]">
                      <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                        {t("settings.dispatch.scheduleTime")}
                        <input
                          type="time"
                          value={scheduleTime}
                          onChange={(event) => setScheduleTime(event.target.value)}
                          className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                        />
                      </label>
                      <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                        {t("settings.dispatch.scheduleDayOfWeek")}
                        <input
                          value={scheduleDayOfWeek}
                          onChange={(event) => setScheduleDayOfWeek(event.target.value)}
                          className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                        />
                      </label>
                    </div>
                    <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                      {t("settings.dispatch.scheduleDescription")}
                      <input
                        value={scheduleDescription}
                        onChange={(event) => setScheduleDescription(event.target.value)}
                        className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text outline-none focus:border-omi-accent"
                      />
                    </label>
                    <label className="flex min-h-9 items-center gap-2 border border-omi-border bg-omi-surface px-3 text-xs font-bold text-omi-text-muted">
                      <input
                        type="checkbox"
                        checked={scheduleEnabled}
                        onChange={(event) => setScheduleEnabled(event.target.checked)}
                        className="h-4 w-4 accent-omi-accent"
                      />
                      {t("settings.dispatch.scheduleEnabled")}
                    </label>
                    <details className="min-w-0 border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
                      <summary className="cursor-pointer text-xs font-black text-omi-text">
                        {t("settings.dispatch.advancedPolicy")}
                      </summary>
                      <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.calendarMode")}
                          <select
                            value={scheduleCalendarMode}
                            onChange={(event) =>
                              setScheduleCalendarMode(
                                event.target.value as DispatchCalendarMode
                              )
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          >
                            {(["calendar_days", "weekdays", "tw_trading_days"] as const).map(
                              (value) => (
                                <option key={value} value={value}>
                                  {t(`settings.dispatch.calendarModes.${value}`)}
                                </option>
                              )
                            )}
                          </select>
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.catchupMode")}
                          <select
                            value={scheduleCatchupMode}
                            onChange={(event) =>
                              setScheduleCatchupMode(
                                event.target.value as DispatchCatchupMode
                              )
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          >
                            <option value="latest_only">
                              {t("settings.dispatch.catchupModes.latest_only")}
                            </option>
                            <option value="all_slots">
                              {t("settings.dispatch.catchupModes.all_slots")}
                            </option>
                          </select>
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.misfirePolicy")}
                          <select
                            value={scheduleMisfirePolicy}
                            onChange={(event) =>
                              setScheduleMisfirePolicy(
                                event.target.value as "catch_up" | "skip"
                              )
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          >
                            <option value="catch_up">
                              {t("settings.dispatch.misfirePolicies.catch_up")}
                            </option>
                            <option value="skip">
                              {t("settings.dispatch.misfirePolicies.skip")}
                            </option>
                          </select>
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.misfireGraceMinutes")}
                          <input
                            type="number"
                            min={0}
                            max={1440}
                            value={scheduleMisfireGraceMinutes}
                            onChange={(event) =>
                              setScheduleMisfireGraceMinutes(Number(event.target.value))
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          />
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.readinessProfile")}
                          <select
                            value={scheduleReadinessProfile}
                            onChange={(event) =>
                              setScheduleReadinessProfile(
                                event.target.value as DispatchReadinessProfile
                              )
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          >
                            {(["generic", "tw_preopen", "tw_post_close", "watchlist_radar"] as const).map(
                              (value) => (
                                <option key={value} value={value}>
                                  {t(`settings.dispatch.readinessProfiles.${value}`)}
                                </option>
                              )
                            )}
                          </select>
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.readinessPolicy")}
                          <select
                            value={scheduleReadinessPolicy}
                            onChange={(event) =>
                              setScheduleReadinessPolicy(
                                event.target.value as DispatchReadinessPolicy
                              )
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          >
                            {(["immediate", "wait_until_ready", "skip_if_incomplete"] as const).map(
                              (value) => (
                                <option key={value} value={value}>
                                  {t(`settings.dispatch.readinessPolicies.${value}`)}
                                </option>
                              )
                            )}
                          </select>
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.readinessDeadlineMinutes")}
                          <input
                            type="number"
                            min={0}
                            max={1440}
                            value={scheduleReadinessDeadlineMinutes}
                            onChange={(event) =>
                              setScheduleReadinessDeadlineMinutes(Number(event.target.value))
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          />
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.readinessRetrySeconds")}
                          <input
                            type="number"
                            min={10}
                            max={3600}
                            value={scheduleReadinessRetrySeconds}
                            onChange={(event) =>
                              setScheduleReadinessRetrySeconds(Number(event.target.value))
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          />
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.maxRetries")}
                          <input
                            type="number"
                            min={0}
                            max={10}
                            value={scheduleMaxRetries}
                            onChange={(event) =>
                              setScheduleMaxRetries(Number(event.target.value))
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          />
                        </label>
                        <label className="grid min-w-0 gap-1 text-xs font-bold text-omi-text-muted">
                          {t("settings.dispatch.retryIntervalSeconds")}
                          <input
                            type="number"
                            min={10}
                            max={3600}
                            value={scheduleRetryIntervalSeconds}
                            onChange={(event) =>
                              setScheduleRetryIntervalSeconds(Number(event.target.value))
                            }
                            className="h-9 min-w-0 w-full border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text outline-none focus:border-omi-accent"
                          />
                        </label>
                      </div>
                    </details>
                    <p className="text-xs leading-5 text-omi-text-muted">
                      {t("settings.dispatch.scheduleDayOfWeekHint")}
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        disabled={savingSchedule || !selectedRecipientGroupId}
                        className="h-9 border border-omi-accent bg-omi-accent px-3 text-sm font-bold text-omi-text-inverse hover:bg-omi-control disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={() => void saveSchedule()}
                      >
                        {savingSchedule
                          ? t("settings.saving")
                          : t("settings.dispatch.saveSchedule")}
                      </button>
                      <button
                        type="button"
                        disabled={
                          !editingScheduleId || deletingScheduleId === editingScheduleId
                        }
                        className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-bold text-omi-text-muted hover:border-omi-danger hover:text-omi-danger disabled:cursor-not-allowed disabled:opacity-50"
                        onClick={() => void deleteSchedule()}
                      >
                        {t("settings.dispatch.deleteSchedule")}
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 grid min-w-0 gap-2">
                    {schedules.length === 0 ? (
                      <StateSurface
                        title={t("settings.dispatch.noSchedules")}
                        tone="empty"
                        compact
                      />
                    ) : (
                      schedules.map((schedule) => (
                        <div
                          key={schedule.id}
                          className={[
                            "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] overflow-hidden border bg-omi-surface-subtle",
                            editingScheduleId === schedule.id
                              ? "border-omi-accent"
                              : "border-omi-border-subtle",
                          ].join(" ")}
                        >
                          <button
                            type="button"
                            className="min-w-0 px-3 py-2 text-left hover:bg-omi-surface"
                            onClick={() => editSchedule(schedule)}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-bold text-omi-text">
                                  {schedule.name}
                                </div>
                                <div className="mt-1 truncate text-xs text-omi-text-muted">
                                  {schedule.send_time} / {schedule.day_of_week} /{" "}
                                  {schedule.recipient_group_name ?? "-"}
                                </div>
                              </div>
                              <span
                                className={[
                                  "shrink-0 text-xs font-black uppercase",
                                  scheduleStatusClassName(schedule),
                                ].join(" ")}
                              >
                                {!schedule.enabled
                                  ? t("settings.dispatch.scheduleDisabledLabel")
                                  : schedule.last_status && schedule.last_status !== "never_run"
                                    ? t(`settings.dispatch.status.${schedule.last_status}`)
                                    : t("settings.dispatch.scheduleEnabledLabel")}
                              </span>
                            </div>
                            <div className="mt-2 grid gap-0.5 text-xs leading-5 text-omi-text-muted">
                              <div>
                                {t("settings.dispatch.nextRun", {
                                  time: formatDateTime(schedule.next_run_at ?? null),
                                })}
                              </div>
                              <div>
                                {t("settings.dispatch.lastQueued", {
                                  time: formatDateTime(schedule.last_queued_at ?? null),
                                })}
                              </div>
                              <div>
                                {t("settings.dispatch.lastSent", {
                                  time: formatDateTime(
                                    schedule.last_sent_at ?? schedule.last_success_at
                                  ),
                                })}
                              </div>
                            </div>
                            {schedule.last_error_message ? (
                              <div className="mt-1 break-words text-xs leading-5 text-omi-danger">
                                {schedule.last_error_message}
                              </div>
                            ) : null}
                          </button>
                          <div className="m-2 grid self-start gap-2">
                            <button
                              type="button"
                              disabled={runningScheduleId === schedule.id}
                              className="h-8 border border-omi-border bg-omi-surface px-2 text-xs font-bold text-omi-text-muted hover:border-omi-control disabled:cursor-not-allowed disabled:opacity-50"
                              onClick={() => void runScheduleNow(schedule.id)}
                            >
                              {runningScheduleId === schedule.id
                                ? t("settings.dispatch.sending")
                                : t("settings.dispatch.runSchedule")}
                            </button>
                            <button
                              type="button"
                              className="h-8 border border-omi-border bg-omi-surface px-2 text-xs font-bold text-omi-text-muted hover:border-omi-control"
                              onClick={() => void toggleScheduleEnabled(schedule)}
                            >
                              {schedule.enabled
                                ? t("settings.dispatch.pauseSchedule")
                                : t("settings.dispatch.resumeSchedule")}
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>

                  {editingScheduleId ? (
                    <div className="mt-5 border-t border-omi-border-subtle pt-4">
                      <div className="flex items-center justify-between gap-3">
                        <h4 className="text-xs font-black uppercase tracking-[0.12em] text-omi-text-muted">
                          {t("settings.dispatch.runHistory")}
                        </h4>
                        <button
                          type="button"
                          className="h-7 border border-omi-border bg-omi-surface px-2 text-xs font-bold text-omi-text-muted hover:border-omi-control"
                          onClick={() => void refreshScheduleRuns(editingScheduleId)}
                        >
                          {t("settings.dispatch.refresh")}
                        </button>
                      </div>
                      <div className="mt-3 grid min-w-0 gap-2">
                        {scheduleRunsState === "loading" ? (
                          <div className="omi-skeleton h-20 w-full" />
                        ) : scheduleRuns.length === 0 ? (
                          <StateSurface
                            title={t("settings.dispatch.noRunHistory")}
                            tone="empty"
                            compact
                          />
                        ) : (
                          scheduleRuns.map((run) => (
                            <div
                              key={run.id}
                              className="min-w-0 overflow-hidden border border-omi-border-subtle bg-omi-surface px-3 py-2"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <div className="text-xs font-bold text-omi-text">
                                    {t(`settings.dispatch.triggerTypes.${run.trigger_type}`)} · #{run.id}
                                  </div>
                                  <div className="mt-1 text-xs text-omi-text-muted">
                                    {formatDateTime(run.scheduled_for)} · {t(
                                      "settings.dispatch.attemptSummary",
                                      {
                                        readiness: run.readiness_check_count,
                                        delivery: run.delivery_attempt_count,
                                        maximum: run.max_delivery_attempts,
                                      }
                                    )}
                                  </div>
                                </div>
                                <span
                                  className={[
                                    "shrink-0 text-xs font-black uppercase",
                                    runStatusClassName(run.status),
                                  ].join(" ")}
                                >
                                  {t(`settings.dispatch.status.${run.status}`)}
                                </span>
                              </div>
                              {readinessReason(run) ? (
                                <div className="mt-2 break-words text-xs leading-5 text-omi-text-muted">
                                  {readinessReason(run)}
                                </div>
                              ) : null}
                              {run.error_message ? (
                                <div className="mt-1 break-words text-xs leading-5 text-omi-danger">
                                  {run.error_code ? `${run.error_code}: ` : ""}
                                  {run.error_message}
                                </div>
                              ) : null}
                              {run.retryable &&
                              ["error", "skipped", "cancelled"].includes(run.status) ? (
                                <button
                                  type="button"
                                  disabled={retryingRunId === run.id}
                                  className="mt-2 h-7 border border-omi-border bg-omi-surface px-2 text-xs font-bold text-omi-text-muted hover:border-omi-control disabled:opacity-50"
                                  onClick={() => void retryScheduleRun(run.id)}
                                >
                                  {t("settings.dispatch.retryRun")}
                                </button>
                              ) : null}
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="mt-5 flex items-center justify-between gap-3">
                  <h3 className="text-sm font-black text-omi-text-strong">
                    {t("settings.dispatch.history")}
                  </h3>
                  <button
                    type="button"
                    className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-bold text-omi-text-muted hover:border-omi-control"
                    onClick={() =>
                      void listDispatchDeliveries(20).then(setDeliveries).catch((error) =>
                        setMessage({
                          type: "error",
                          text:
                            error instanceof Error
                              ? error.message
                              : t("settings.dispatch.loadError"),
                        })
                      )
                    }
                  >
                    {t("settings.dispatch.refresh")}
                  </button>
                </div>
                <div className="mt-3 grid min-w-0 gap-2">
                  {deliveries.length === 0 ? (
                    <StateSurface
                      title={t("settings.dispatch.noHistory")}
                      tone="empty"
                      compact
                    />
                  ) : (
                    deliveries.map((delivery) => (
                      <div
                        key={delivery.id}
                        className="min-w-0 overflow-hidden border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2"
                      >
                        <div className="flex min-w-0 items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-bold text-omi-text">
                              {delivery.subject}
                            </div>
                            <div className="mt-1 text-xs text-omi-text-muted">
                              {formatDateTime(delivery.created_at)} /{" "}
                              {t("settings.dispatch.emailCount", {
                                count: delivery.recipient_count,
                              })}
                            </div>
                          </div>
                          <div
                            className={[
                              "shrink-0 text-xs font-black uppercase",
                              deliveryStatusClassName(delivery.status),
                            ].join(" ")}
                          >
                            {t(`settings.dispatch.status.${delivery.status}`)}
                          </div>
                        </div>
                        {delivery.error_message ? (
                          <div className="mt-2 break-words text-xs leading-5 text-omi-danger">
                            {delivery.error_message}
                          </div>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>
          </main>
        </div>
      </section>
    </div>
  );
}

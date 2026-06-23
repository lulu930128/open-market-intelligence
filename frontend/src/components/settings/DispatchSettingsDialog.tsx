"use client";

import { useT } from "@/i18n";
import {
  createDispatchRecipientGroup,
  deleteDispatchRecipientGroup,
  listDispatchDeliveries,
  listDispatchRecipientGroups,
  listDispatchWatchlistGroups,
  previewDispatch,
  sendDispatch,
  updateDispatchRecipientGroup,
  type DispatchDeliveryRead,
  type DispatchMarket,
  type DispatchPreviewRead,
  type DispatchPreviewRequest,
  type DispatchRecipientGroupRead,
  type DispatchTemplateKey,
  type WatchlistGroupOption,
} from "@/lib/dispatchMail";
import { useCallback, useEffect, useMemo, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type ActionState = "idle" | "loading" | "error";
type PreviewMode = "html" | "text";

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
  if (status === "error") return "text-omi-danger";
  if (status === "sending" || status === "queued") return "text-omi-accent";
  return "text-omi-text-muted";
}

function toTextAreaValue(emails: string[]) {
  return emails.join("\n");
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
  const [preview, setPreview] = useState<DispatchPreviewRead | null>(null);
  const [previewMode, setPreviewMode] = useState<PreviewMode>("html");
  const [savingGroup, setSavingGroup] = useState(false);
  const [deletingGroup, setDeletingGroup] = useState(false);
  const [sending, setSending] = useState(false);

  const selectedRecipientGroup = useMemo(
    () =>
      recipientGroups.find((group) => group.id === selectedRecipientGroupId) ?? null,
    [recipientGroups, selectedRecipientGroupId]
  );

  const activeWatchlistGroups = useMemo(
    () => watchlistGroups.filter((group) => group.is_active),
    [watchlistGroups]
  );

  const loadData = useCallback(async () => {
    await Promise.resolve();
    setLoadState("loading");
    setActionState("idle");
    setMessage(null);

    try {
      const [nextRecipientGroups, nextDeliveries, nextWatchlistGroups] =
        await Promise.all([
          listDispatchRecipientGroups(),
          listDispatchDeliveries(20),
          listDispatchWatchlistGroups(market),
        ]);

      setRecipientGroups(nextRecipientGroups);
      setDeliveries(nextDeliveries);
      setWatchlistGroups(nextWatchlistGroups);
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
      };
    }

    return {
      template_key: "market_overview",
      scope_type: "market",
      scope_id: market,
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
              "shrink-0 border-b px-5 py-2 text-sm font-semibold",
              message.type === "error"
                ? "border-omi-danger-border bg-omi-danger-soft text-omi-danger"
                : "border-omi-success-border bg-omi-success-soft text-omi-success",
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
                <div className="border border-omi-border-subtle bg-omi-surface px-3 py-3 text-xs text-omi-text-muted">
                  {t("settings.dispatch.noRecipientGroups")}
                </div>
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
                  {templateKey === "watchlist_brief" ? (
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
                  <div className="mt-3 flex h-[260px] items-center justify-center border border-omi-border-subtle bg-omi-surface-subtle px-4 text-center text-sm text-omi-text-muted">
                    {t("settings.dispatch.emptyPreview")}
                  </div>
                )}
              </section>

              <section className="min-h-0 overflow-y-auto p-5">
                <div className="flex items-center justify-between gap-3">
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
                <div className="mt-3 grid gap-2">
                  {deliveries.length === 0 ? (
                    <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3 text-xs text-omi-text-muted">
                      {t("settings.dispatch.noHistory")}
                    </div>
                  ) : (
                    deliveries.map((delivery) => (
                      <div
                        key={delivery.id}
                        className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2"
                      >
                        <div className="flex items-start justify-between gap-3">
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

"use client";

import { useEffect, useMemo, useState } from "react";

import { useT } from "@/i18n";
import { ApiError, fetchJson } from "@/lib/api";
import type { BackendConnectionIssueCode } from "@/types/runtime";

type ReadinessPayload = {
  status?: string;
};

type ConnectionState = "unknown" | "online" | "offline";

const READY_CHECK_INTERVAL_MS = 15_000;
const READY_CHECK_TIMEOUT_MS = 3_000;

function issueMessageKey(code: BackendConnectionIssueCode | null) {
  if (code === "timeout") return "dashboard.connection.issueTimeout";
  if (code === "invalid_response") return "dashboard.connection.issueInvalidResponse";
  if (code === "request_failed") return "dashboard.connection.issueRequestFailed";
  return "dashboard.connection.issueUnavailable";
}

export default function BackendConnectionBanner({
  initialIssueCount,
  initialIssueCode,
  formIssueCode,
}: {
  initialIssueCount: number;
  initialIssueCode: BackendConnectionIssueCode | null;
  formIssueCode: BackendConnectionIssueCode | null;
}) {
  const t = useT();
  const [connectionState, setConnectionState] = useState<ConnectionState>("unknown");
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!formIssueCode) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("omi_error");
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`
    );
  }, [formIssueCode]);

  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;

    async function checkReadiness() {
      controller?.abort();
      const requestController = new AbortController();
      controller = requestController;

      try {
        const payload = await fetchJson<ReadinessPayload>(
          "/api/system/readyz",
          undefined,
          { signal: requestController.signal, timeoutMs: READY_CHECK_TIMEOUT_MS }
        );
        if (active) setConnectionState(payload.status === "ready" ? "online" : "offline");
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          try {
            await fetchJson("/api/system/health", undefined, {
              signal: requestController.signal,
              timeoutMs: READY_CHECK_TIMEOUT_MS,
            });
            if (active) setConnectionState("online");
            return;
          } catch {
            // Fall through to the offline state for rolling-upgrade compatibility.
          }
        }
        if (!requestController.signal.aborted && active) setConnectionState("offline");
      }
    }

    void checkReadiness();
    const intervalId = window.setInterval(checkReadiness, READY_CHECK_INTERVAL_MS);

    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(intervalId);
    };
  }, []);

  const content = useMemo(() => {
    if (connectionState === "offline") {
      return {
        tone: "error" as const,
        title: t("dashboard.connection.offlineTitle"),
        message: t("dashboard.connection.offlineMessage"),
      };
    }

    if (formIssueCode) {
      return {
        tone: "error" as const,
        title: t("dashboard.connection.operationFailedTitle"),
        message: t(issueMessageKey(formIssueCode)),
      };
    }

    if (initialIssueCount > 0) {
      return {
        tone: "warning" as const,
        title: t("dashboard.connection.partialTitle"),
        message: t("dashboard.connection.partialMessage", {
          count: initialIssueCount,
          reason: t(issueMessageKey(initialIssueCode)),
        }),
      };
    }

    return null;
  }, [connectionState, formIssueCode, initialIssueCode, initialIssueCount, t]);

  if (!content || (dismissed && connectionState !== "offline")) return null;

  const toneClass =
    content.tone === "error"
      ? "border-omi-danger-border bg-omi-danger-soft text-omi-danger"
      : "border-omi-warning-border bg-omi-warning-soft text-omi-warning";

  return (
    <section
      data-testid="backend-connection-banner"
      role="alert"
      className={`flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2.5 text-sm ${toneClass}`}
    >
      <div className="min-w-0">
        <div className="font-bold">{content.title}</div>
        <div className="mt-0.5 text-xs opacity-90">{content.message}</div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded border border-current px-3 py-1 text-xs font-bold transition hover:bg-white/10"
        >
          {t("dashboard.connection.reload")}
        </button>
        {connectionState !== "offline" ? (
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="rounded px-2 py-1 text-xs font-bold opacity-80 transition hover:opacity-100"
          >
            {t("common.close")}
          </button>
        ) : null}
      </div>
    </section>
  );
}

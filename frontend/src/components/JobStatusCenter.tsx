"use client";

import { fetchJson, requestJson } from "@/lib/api";
import {
  subscribeDataStatusEvents,
  subscribeDataStatusFocus,
  type DataStatusFocus,
  type DataStatusEvent,
  type DataStatusLevel,
} from "@/lib/dataStatusEvents";
import { formatJobStatus } from "@/lib/jobs";
import { useT, type TranslationFunction } from "@/i18n";
import type { JobRunRead } from "@/types/market";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const ACTIVE_STATUSES = new Set(["queued", "running"]);

type JobMarketFilter = "all" | "tw" | "us" | "jp" | "kr" | "crypto";

const NON_RETRYABLE_JOB_TYPES = new Set(["market.tw_futures_quote_refresh"]);

function getJobMarket(jobType: string): "tw" | "us" | "jp" | "kr" | "crypto" | "other" {
  if (jobType.startsWith("us_market.") || jobType === "scheduler.us_market_daily_refresh") {
    return "us";
  }

  if (jobType.startsWith("jp_market.")) {
    return "jp";
  }

  if (jobType.startsWith("kr_market.")) {
    return "kr";
  }

  if (jobType.startsWith("crypto_market.") || jobType.startsWith("resource_market.")) {
    return "crypto";
  }

  if (
    jobType.startsWith("market.") ||
    jobType.startsWith("watchlist.") ||
    jobType === "scheduler.market_daily_refresh" ||
    jobType === "scheduler.market_chip_daily_refresh"
  ) {
    return "tw";
  }

  return "other";
}

function getJobTypeLabel(t: TranslationFunction, jobType: string) {
  const key = `jobs.types.${jobType}`;
  const label = t(key);
  return label === key ? jobType : label;
}

function isActiveJob(job: JobRunRead) {
  return ACTIVE_STATUSES.has(job.status);
}

function getResultObject(job: JobRunRead) {
  if (!job.result || typeof job.result !== "object" || Array.isArray(job.result)) {
    return null;
  }

  return job.result as Record<string, unknown>;
}

function getResultNumber(job: JobRunRead, key: string) {
  const value = getResultObject(job)?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getFirstResultNumber(job: JobRunRead, keys: string[]) {
  for (const key of keys) {
    const value = getResultNumber(job, key);

    if (value !== null) return value;
  }

  return null;
}

function getResultString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function getResultItems(job: JobRunRead) {
  const result = getResultObject(job);
  const rows = result?.results;

  if (!Array.isArray(rows)) return [];

  return rows.filter(
    (row): row is Record<string, unknown> =>
      typeof row === "object" && row !== null && !Array.isArray(row)
  );
}

function getResultErrors(job: JobRunRead) {
  const result = getResultObject(job);
  const rows = result?.errors;

  if (!Array.isArray(rows)) return [];

  return rows.filter(
    (row): row is Record<string, unknown> =>
      typeof row === "object" && row !== null && !Array.isArray(row)
  );
}

function getFailedResultItems(job: JobRunRead) {
  const failedRows = getResultItems(job).filter((row) => {
    const status = getResultString(row.status);
    const errorMessage = getResultString(row.error_message);

    return status === "error" || status === "partial_success" || errorMessage !== null;
  });

  return [...failedRows, ...getResultErrors(job)];
}

function getFailedUnitCount(job: JobRunRead) {
  const failedItems = getFailedResultItems(job).length;
  if (failedItems > 0) return failedItems;

  const errorCount = getFirstResultNumber(job, ["error_count", "failed_count"]);
  if (errorCount !== null && errorCount > 0) return errorCount;

  const effectiveStatus = getEffectiveStatus(job);
  if (effectiveStatus === "error" || effectiveStatus === "partial_success") return 1;

  return 0;
}

function hasResultErrors(job: JobRunRead) {
  const errorCount = getFirstResultNumber(job, ["error_count", "failed_count"]);
  return (
    (errorCount !== null && errorCount > 0) ||
    getFailedResultItems(job).length > 0
  );
}

function getEffectiveStatus(job: JobRunRead) {
  const resultStatus = getResultObject(job)?.status;

  if (job.status === "success" && typeof resultStatus === "string") {
    return resultStatus;
  }

  if (job.status === "success" && hasResultErrors(job)) {
    return "partial_success";
  }

  return job.status;
}

function getEffectiveStatusLabel(job: JobRunRead, t: TranslationFunction) {
  const effectiveStatus = getEffectiveStatus(job);
  const key = `jobs.status.${effectiveStatus}`;
  const label = t(key);

  return label === key ? effectiveStatus : label;
}

function formatDateTime(value: string | null) {
  if (!value) return "-";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function statusTone(job: JobRunRead) {
  const effectiveStatus = getEffectiveStatus(job);

  if (effectiveStatus === "error") return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  if (isActiveJob(job)) return "border-omi-info-border bg-omi-info-soft text-omi-info";

  if (effectiveStatus === "partial_success") {
    return "border-omi-warning-border bg-omi-warning-soft text-omi-warning";
  }

  return "border-omi-success-border bg-omi-success-soft text-omi-success";
}

function dataStatusTone(level: DataStatusLevel) {
  if (level === "error") return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  if (level === "warning") return "border-omi-warning-border bg-omi-warning-soft text-omi-warning";
  if (level === "success") return "border-omi-success-border bg-omi-success-soft text-omi-success";
  return "border-omi-info-border bg-omi-info-soft text-omi-info";
}

function dataStatusLevelLabel(level: DataStatusLevel) {
  if (level === "error") return "資料失敗";
  if (level === "warning") return "資料警示";
  if (level === "success") return "資料完成";
  return "資料狀態";
}

function canRetry(job: JobRunRead) {
  const effectiveStatus = getEffectiveStatus(job);
  return (
    !NON_RETRYABLE_JOB_TYPES.has(job.job_type) &&
    (effectiveStatus === "error" || effectiveStatus === "partial_success")
  );
}

function buildStatusSummary(t: TranslationFunction, activeCount: number, failedCount: number) {
  if (activeCount > 0) {
    return {
      className: "omi-job-status-pill-active",
      label: t("jobs.summary.active", { count: activeCount }),
    };
  }

  if (failedCount > 0) {
    return {
      className: "omi-job-status-pill-attention",
      label: t("jobs.summary.attention", { count: failedCount }),
    };
  }

  return {
    className: "omi-job-status-pill-idle",
    label: t("jobs.summary.idle"),
  };
}

function isAttentionDataStatus(event: DataStatusEvent) {
  return event.level === "error" || event.level === "warning";
}

function isActiveDataStatus(event: DataStatusEvent) {
  return event.level === "info";
}

function formatShortText(value: string | null, maxLength = 220) {
  if (!value) return null;

  return value.length > maxLength ? `${value.slice(0, maxLength).trimEnd()}...` : value;
}

function formatResultSummary(job: JobRunRead, t: TranslationFunction) {
  const requestedCount = getFirstResultNumber(job, [
    "requested_count",
    "requested_stock_count",
    "requested_symbol_count",
    "symbol_count",
    "total_symbol_count",
    "total_count",
  ]);
  const successCount = getFirstResultNumber(job, [
    "success_count",
    "current_count",
    "refreshed_symbol_count",
    "complete_symbol_count",
  ]);
  const partialCount = getFirstResultNumber(job, [
    "partial_symbol_count",
    "partial_success_count",
  ]);
  const warningCount = getFirstResultNumber(job, ["warning_count"]);
  const errorCount =
    getFirstResultNumber(job, ["failed_symbol_count", "error_count", "failed_count"]) ??
    getResultErrors(job).length;
  const resourceSuccessCount = getFirstResultNumber(job, ["resource_success_count"]);
  const resourceErrorCount = getFirstResultNumber(job, ["resource_error_count"]);
  const insertedCount = getFirstResultNumber(job, ["inserted_count"]);
  const updatedCount = getFirstResultNumber(job, ["updated_count"]);
  const fetchedCount = getFirstResultNumber(job, ["fetched_count"]);
  const skippedExistingCount = getFirstResultNumber(job, [
    "skipped_existing_count",
    "skipped_count",
  ]);
  const parts: string[] = [];

  if (requestedCount !== null && errorCount !== null) {
    parts.push(
      t("jobs.result.completed", {
        current: Math.max(requestedCount - errorCount, 0),
        total: requestedCount,
      })
    );
  } else if (requestedCount !== null && successCount !== null) {
    parts.push(
      t("jobs.result.completed", {
        current: successCount,
        total: requestedCount,
      })
    );
  }

  if (partialCount !== null && partialCount > 0) {
    parts.push(t("jobs.result.partial", { count: partialCount }));
  }
  if (resourceSuccessCount !== null && resourceSuccessCount > 0) {
    parts.push(t("jobs.result.resourceSuccess", { count: resourceSuccessCount }));
  }
  if (resourceErrorCount !== null && resourceErrorCount > 0) {
    parts.push(t("jobs.result.resourceErrors", { count: resourceErrorCount }));
  }
  if (insertedCount !== null && insertedCount > 0) {
    parts.push(t("jobs.result.inserted", { count: insertedCount }));
  }
  if (updatedCount !== null && updatedCount > 0) {
    parts.push(t("jobs.result.updated", { count: updatedCount }));
  }
  if (fetchedCount !== null && fetchedCount > 0) {
    parts.push(t("jobs.result.fetched", { count: fetchedCount }));
  }
  if (skippedExistingCount !== null && skippedExistingCount > 0) {
    parts.push(t("jobs.result.skippedExisting", { count: skippedExistingCount }));
  }
  if (warningCount !== null && warningCount > 0) {
    parts.push(t("jobs.result.warnings", { count: warningCount }));
  }
  if (errorCount !== null && errorCount > 0) {
    parts.push(t("jobs.result.failed", { count: errorCount }));
  }

  return parts;
}

function formatResultItemTitle(row: Record<string, unknown>, t: TranslationFunction) {
  const stockId = getResultString(row.stock_id);
  const stockName = getResultString(row.stock_name);
  const symbol = getResultString(row.symbol);
  const resource = getResultString(row.resource);
  const sourceName = getResultString(row.source_name);
  const category = getResultString(row.category);
  const tradeDate = getResultString(row.trade_date);
  const title =
    stockId !== null
      ? `${stockId}${stockName ? ` ${stockName}` : ""}`
      : symbol !== null
        ? `${symbol}${resource ? ` · ${resource}` : ""}`
      : sourceName ?? category ?? t("jobs.itemFallback");

  return tradeDate ? `${title} · ${tradeDate}` : title;
}

function formatResultItemMessage(row: Record<string, unknown>, t: TranslationFunction) {
  return (
    getResultString(row.error_message) ??
    getResultString(row.message) ??
    getResultString(row.status) ??
    t("jobs.unfinished")
  );
}

function JobRow({
  job,
  retryingJobId,
  onRetry,
  t,
}: {
  job: JobRunRead;
  retryingJobId: number | null;
  onRetry: (job: JobRunRead) => void;
  t: TranslationFunction;
}) {
  const summaryParts = formatResultSummary(job, t);
  const failedItems = getFailedResultItems(job);
  const visibleFailedItems = failedItems.slice(0, 4);
  const errorMessage = formatShortText(job.error_message);

  return (
    <div className="border-t border-omi-border-subtle px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-omi-text">
            {getJobTypeLabel(t, job.job_type)}
            {job.target ? <span className="ml-1 text-omi-text-muted">#{job.target}</span> : null}
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">{formatJobStatus(job, t)}</div>
        </div>
        <span className={`shrink-0 border px-2 py-1 text-[11px] font-bold ${statusTone(job)}`}>
          {getEffectiveStatusLabel(job, t)}
        </span>
      </div>

      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-omi-text-muted">
        <span>{t("jobs.updatedAt", { time: formatDateTime(job.updated_at) })}</span>
      </div>

      {summaryParts.length ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {summaryParts.map((part) => (
            <span key={part} className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-0.5 text-[11px] text-omi-text-muted">
              {part}
            </span>
          ))}
        </div>
      ) : null}

      {visibleFailedItems.length ? (
        <div className="mt-2 space-y-1">
          {visibleFailedItems.map((row, index) => (
            <div key={`${formatResultItemTitle(row, t)}-${index}`} className="border border-omi-danger-border bg-omi-danger-soft px-2 py-1 text-xs text-omi-danger">
              <div className="font-bold">{formatResultItemTitle(row, t)}</div>
              <div className="mt-0.5 break-words text-[11px]">
                {formatShortText(formatResultItemMessage(row, t))}
              </div>
            </div>
          ))}
          {failedItems.length > visibleFailedItems.length ? (
            <div className="text-[11px] text-omi-text-muted">
              {t("jobs.moreFailedItems", {
                count: failedItems.length - visibleFailedItems.length,
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      {errorMessage ? (
        <div className="mt-2 break-words border border-omi-danger-border bg-omi-danger-soft px-2 py-1 text-xs text-omi-danger">
          {errorMessage}
        </div>
      ) : null}

      {canRetry(job) ? (
        <button
          type="button"
          className="mt-2 border border-omi-border px-2 py-1 text-xs font-bold text-omi-text hover:border-omi-border-strong disabled:cursor-not-allowed disabled:opacity-50"
          disabled={retryingJobId === job.id}
          onClick={() => onRetry(job)}
        >
          {retryingJobId === job.id ? t("jobs.retrying") : t("jobs.retry")}
        </button>
      ) : null}
    </div>
  );
}

function DataStatusEventRow({ event }: { event: DataStatusEvent }) {
  return (
    <div className="border-t border-omi-border-subtle px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-omi-text">{event.title}</div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {event.source} · {formatDateTime(event.createdAt)}
          </div>
        </div>
        <span className={`shrink-0 border px-2 py-1 text-[11px] font-bold ${dataStatusTone(event.level)}`}>
          {dataStatusLevelLabel(event.level)}
        </span>
      </div>
      <div className="mt-2 break-words text-xs text-omi-text-muted">{event.message}</div>
    </div>
  );
}

function DataStatusSection({
  title,
  subtitle,
  empty,
  events,
}: {
  title: string;
  subtitle?: string | null;
  empty: string;
  events: DataStatusEvent[];
}) {
  return (
    <div className="border-t border-omi-border-subtle">
      <div className="bg-omi-surface-subtle px-3 py-2">
        <div className="text-[11px] font-black uppercase tracking-[0.14em] text-omi-text-muted">
          {title}
        </div>
        {subtitle ? (
          <div className="mt-0.5 truncate text-xs font-semibold text-omi-text">
            {subtitle}
          </div>
        ) : null}
      </div>
      {events.length ? (
        events.map((event) => <DataStatusEventRow key={event.id} event={event} />)
      ) : (
        <div className="border-t border-omi-border-subtle px-3 py-3 text-xs text-omi-text-muted">
          {empty}
        </div>
      )}
    </div>
  );
}

type JobStatusCenterProps = {
  placement?: "fixed" | "inline";
  market?: JobMarketFilter;
};

export default function JobStatusCenter({
  placement = "fixed",
  market = "all",
}: JobStatusCenterProps) {
  const t = useT();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<JobRunRead[]>([]);
  const [dataStatusEvents, setDataStatusEvents] = useState<DataStatusEvent[]>([]);
  const [dataStatusFocus, setDataStatusFocus] = useState<DataStatusFocus | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<number | null>(null);
  const inline = placement === "inline";

  const loadJobs = useCallback(async () => {
    try {
      const rows = await fetchJson<JobRunRead[]>("/api/jobs", {
        limit: market === "all" ? 20 : 80,
        include_payload: false,
      });
      const marketRows =
        market === "all"
          ? rows
          : rows.filter((job) => getJobMarket(job.job_type) === market);

      setJobs(marketRows.slice(0, 20));
      setErrorMessage(null);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t("jobs.loadError"));
    }
  }, [market, t]);

  useEffect(() => {
    const initialTimer = window.setTimeout(() => {
      void loadJobs();
    }, 0);

    const interval = window.setInterval(() => {
      void loadJobs();
    }, open ? 3000 : 10000);

    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(interval);
    };
  }, [loadJobs, open]);

  useEffect(() => {
    return subscribeDataStatusEvents(market, setDataStatusEvents);
  }, [market]);

  useEffect(() => {
    return subscribeDataStatusFocus(market, setDataStatusFocus);
  }, [market]);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (target instanceof Node && rootRef.current?.contains(target)) {
        return;
      }

      setOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [open]);

  const activeCount = useMemo(() => jobs.filter(isActiveJob).length, [jobs]);
  const focusedDataStatusEvents = useMemo(
    () =>
      dataStatusFocus
        ? dataStatusEvents.filter((event) => event.contextKey === dataStatusFocus.contextKey)
        : [],
    [dataStatusEvents, dataStatusFocus]
  );
  const backgroundDataStatusEvents = useMemo(
    () =>
      dataStatusFocus
        ? dataStatusEvents.filter((event) => event.contextKey !== dataStatusFocus.contextKey)
        : dataStatusEvents,
    [dataStatusEvents, dataStatusFocus]
  );
  const panelText = useMemo(
    () => ({
      subtitle: t(`jobs.panel.${market}Subtitle`),
      empty: t(`jobs.panel.${market}Empty`),
    }),
    [market, t]
  );
  const failedCount = useMemo(
    () =>
      dataStatusFocus
        ? focusedDataStatusEvents.filter(isAttentionDataStatus).length
        : jobs.reduce((count, job) => count + getFailedUnitCount(job), 0) +
          backgroundDataStatusEvents.filter(isAttentionDataStatus).length,
    [backgroundDataStatusEvents, dataStatusFocus, focusedDataStatusEvents, jobs]
  );
  const summaryActiveCount = useMemo(
    () =>
      dataStatusFocus
        ? focusedDataStatusEvents.filter(isActiveDataStatus).length
        : activeCount,
    [activeCount, dataStatusFocus, focusedDataStatusEvents]
  );
  const statusSummary = useMemo(
    () => buildStatusSummary(t, summaryActiveCount, failedCount),
    [failedCount, summaryActiveCount, t]
  );

  async function handleRetry(job: JobRunRead) {
    setRetryingJobId(job.id);

    try {
      await requestJson<JobRunRead>(`/api/jobs/${job.id}/retry`, { method: "POST" });
      await loadJobs();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t("jobs.retryError"));
    } finally {
      setRetryingJobId(null);
    }
  }

  return (
    <div ref={rootRef} className={inline ? "relative" : "fixed right-6 top-4 z-50"}>
      <button
        type="button"
        aria-expanded={open}
        className={[
          "flex min-w-[104px] items-center justify-between gap-2 border border-omi-border bg-omi-surface px-3 py-2 text-sm font-bold text-omi-text shadow-sm hover:border-omi-border-strong",
          inline ? "w-full" : "",
        ].join(" ")}
        onClick={() => setOpen((value) => !value)}
      >
        <span>{t("jobs.button")}</span>
        <span className={`omi-job-status-pill ${statusSummary.className}`}>
          {statusSummary.label}
        </span>
      </button>

      {open ? (
        <section
          className={[
            "mt-2 border border-omi-border bg-omi-surface shadow-xl",
            inline ? "w-full" : "w-[420px]",
          ].join(" ")}
        >
          <div className="flex items-start justify-between gap-2 border-b border-omi-border-subtle px-3 py-2">
            <div className="min-w-0">
              <h2 className="text-sm font-black text-omi-text-strong">{t("jobs.panelTitle")}</h2>
              <p className="text-xs text-omi-text-muted">{panelText.subtitle}</p>
            </div>
            <button
              type="button"
              className="h-7 shrink-0 whitespace-nowrap border border-omi-border px-2 text-[11px] font-bold text-omi-text hover:border-omi-border-strong"
              onClick={() => void loadJobs()}
            >
              {t("jobs.refresh")}
            </button>
          </div>

          {errorMessage ? (
            <div className="border-b border-omi-danger-border bg-omi-danger-soft px-3 py-2 text-xs text-omi-danger">
              {errorMessage}
            </div>
          ) : null}

          <div className={inline ? "max-h-72 overflow-y-auto" : "max-h-[520px] overflow-y-auto"}>
            {dataStatusFocus ? (
              <>
                <DataStatusSection
                  title={t("jobs.scope.current")}
                  subtitle={dataStatusFocus.label}
                  empty={t("jobs.scope.currentEmpty", { label: dataStatusFocus.label })}
                  events={focusedDataStatusEvents.slice(0, 4)}
                />
                {backgroundDataStatusEvents.length ? (
                  <DataStatusSection
                    title={t("jobs.scope.background")}
                    empty={t("jobs.scope.backgroundEmpty")}
                    events={backgroundDataStatusEvents.slice(0, 4)}
                  />
                ) : null}
              </>
            ) : dataStatusEvents.length ? (
              dataStatusEvents
                .slice(0, 6)
                .map((event) => <DataStatusEventRow key={event.id} event={event} />)
            ) : null}
            {jobs.length ? (
              <div className="border-t border-omi-border-subtle">
                <div className="bg-omi-surface-subtle px-3 py-2 text-[11px] font-black uppercase tracking-[0.14em] text-omi-text-muted">
                  {t("jobs.scope.jobs")}
                </div>
                {jobs.map((job) => (
                  <JobRow key={job.id} job={job} retryingJobId={retryingJobId} onRetry={handleRetry} t={t} />
                ))}
              </div>
            ) : null}
            {!jobs.length && !dataStatusEvents.length && !dataStatusFocus ? (
              <div className="px-3 py-8 text-center text-sm text-omi-text-muted">
                {panelText.empty}
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

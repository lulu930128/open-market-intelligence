"use client";

import { fetchJson, requestJson } from "@/lib/api";
import { formatJobStatus } from "@/lib/jobs";
import type { JobRunRead } from "@/types/market";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const ACTIVE_STATUSES = new Set(["queued", "running"]);

const JOB_TYPE_LABELS: Record<string, string> = {
  "market.stock_selection_refresh": "自選股資料更新",
  "watchlist.group_daily_price_refresh_latest": "自選股日線補齊",
  "watchlist.group_daily_price_backfill": "自選股歷史日線",
  "market.daily_metrics_backfill": "法人 / 融資融券",
  "scheduler.market_daily_refresh": "排程法人 / 融資融券",
  "market.stock_daily_metrics_history_backfill": "個股籌碼歷史",
  "market.stock_shareholding_history_backfill": "股權分散歷史",
  "market.stock_monthly_revenue_history_backfill": "營收歷史",
  "market.stock_financial_metrics_history_backfill": "盈餘歷史",
  "market.stock_fundamental_metrics_backfill": "個股基本資料",
  "market.fundamental_metrics_backfill": "市場基本資料",
  "market.twse_daily_price_backfill": "上市日線補齊",
  "market.tpex_daily_price_backfill": "上櫃日線補齊",
};

function getJobTypeLabel(jobType: string) {
  return JOB_TYPE_LABELS[jobType] ?? jobType;
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

function getEffectiveStatus(job: JobRunRead) {
  const resultStatus = getResultObject(job)?.status;
  return job.status === "success" && typeof resultStatus === "string" ? resultStatus : job.status;
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

  if (effectiveStatus === "error") return "border-red-200 bg-red-50 text-red-700";
  if (isActiveJob(job)) return "border-blue-200 bg-blue-50 text-blue-700";

  if (effectiveStatus === "partial_success") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  return "border-emerald-200 bg-emerald-50 text-emerald-700";
}

function canRetry(job: JobRunRead) {
  const effectiveStatus = getEffectiveStatus(job);
  return effectiveStatus === "error" || effectiveStatus === "partial_success";
}

function JobRow({
  job,
  retryingJobId,
  onRetry,
}: {
  job: JobRunRead;
  retryingJobId: number | null;
  onRetry: (job: JobRunRead) => void;
}) {
  const errorCount = getResultNumber(job, "error_count");
  const requestedCount = getResultNumber(job, "requested_count");
  const summary =
    errorCount !== null && requestedCount !== null
      ? `來源 ${requestedCount - errorCount}/${requestedCount}`
      : null;

  return (
    <div className="border-t border-slate-200 px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-slate-900">
            {getJobTypeLabel(job.job_type)}
            {job.target ? <span className="ml-1 text-slate-500">#{job.target}</span> : null}
          </div>
          <div className="mt-1 text-xs text-slate-600">{formatJobStatus(job)}</div>
        </div>
        <span className={`shrink-0 border px-2 py-1 text-[11px] font-bold ${statusTone(job)}`}>
          {getEffectiveStatus(job)}
        </span>
      </div>

      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-slate-500">
        <span>更新 {formatDateTime(job.updated_at)}</span>
        {summary ? <span>{summary}</span> : null}
      </div>

      {job.error_message ? (
        <div className="mt-2 break-words border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">
          {job.error_message}
        </div>
      ) : null}

      {canRetry(job) ? (
        <button
          type="button"
          className="mt-2 border border-slate-300 px-2 py-1 text-xs font-bold text-slate-700 hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={retryingJobId === job.id}
          onClick={() => onRetry(job)}
        >
          {retryingJobId === job.id ? "重新排程中" : "重新排程"}
        </button>
      ) : null}
    </div>
  );
}

type JobStatusCenterProps = {
  placement?: "fixed" | "inline";
};

export default function JobStatusCenter({ placement = "fixed" }: JobStatusCenterProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<JobRunRead[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<number | null>(null);
  const inline = placement === "inline";

  const loadJobs = useCallback(async () => {
    try {
      const rows = await fetchJson<JobRunRead[]>("/api/jobs", { limit: 20 });
      setJobs(rows);
      setErrorMessage(null);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "工作狀態讀取失敗");
    }
  }, []);

  useEffect(() => {
    const initialTimer = window.setTimeout(() => {
      void loadJobs();
    }, 0);

    const interval = window.setInterval(() => {
      void loadJobs();
    }, 3000);

    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(interval);
    };
  }, [loadJobs]);

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
  const failedCount = useMemo(
    () =>
      jobs.filter((job) => {
        const effectiveStatus = getEffectiveStatus(job);
        return effectiveStatus === "error" || effectiveStatus === "partial_success";
      }).length,
    [jobs]
  );

  async function handleRetry(job: JobRunRead) {
    setRetryingJobId(job.id);

    try {
      await requestJson<JobRunRead>(`/api/jobs/${job.id}/retry`, { method: "POST" });
      await loadJobs();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "重新排程失敗");
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
          "flex min-w-[104px] items-center justify-between gap-2 border border-slate-300 bg-white px-3 py-2 text-sm font-bold text-slate-800 shadow-sm hover:border-slate-500",
          inline ? "w-full" : "",
        ].join(" ")}
        onClick={() => setOpen((value) => !value)}
      >
        <span>更新狀態</span>
        <span
          className={
            activeCount
              ? "bg-blue-600 px-2 py-0.5 text-xs text-white"
              : failedCount
                ? "bg-amber-500 px-2 py-0.5 text-xs text-white"
                : "bg-slate-200 px-2 py-0.5 text-xs text-slate-700"
          }
        >
          {activeCount || failedCount || "OK"}
        </span>
      </button>

      {open ? (
        <section
          className={[
            "mt-2 border border-slate-300 bg-white shadow-xl",
            inline ? "w-full" : "w-[420px]",
          ].join(" ")}
        >
          <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
            <div>
              <h2 className="text-sm font-black text-slate-950">背景工作</h2>
              <p className="text-xs text-slate-500">顯示最近 20 筆補資料與排程工作</p>
            </div>
            <button
              type="button"
              className="border border-slate-300 px-2 py-1 text-xs font-bold text-slate-700 hover:border-slate-500"
              onClick={() => void loadJobs()}
            >
              重整
            </button>
          </div>

          {errorMessage ? (
            <div className="border-b border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {errorMessage}
            </div>
          ) : null}

          <div className={inline ? "max-h-72 overflow-y-auto" : "max-h-[520px] overflow-y-auto"}>
            {jobs.length ? (
              jobs.map((job) => (
                <JobRow key={job.id} job={job} retryingJobId={retryingJobId} onRetry={handleRetry} />
              ))
            ) : (
              <div className="px-3 py-8 text-center text-sm text-slate-500">尚無背景工作</div>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}

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
  "market.market_chip_daily_refresh": "大盤籌碼日報",
  "scheduler.market_chip_daily_refresh": "排程大盤籌碼日報",
  "market.tw_futures_quote_refresh": "台指期報價更新",
  "market.stock_daily_metrics_history_backfill": "個股籌碼歷史",
  "market.stock_shareholding_history_backfill": "股權分散歷史",
  "market.stock_monthly_revenue_history_backfill": "營收歷史",
  "market.stock_financial_metrics_history_backfill": "盈餘歷史",
  "market.stock_fundamental_metrics_backfill": "個股基本資料",
  "market.fundamental_metrics_backfill": "市場基本資料",
  "market.twse_daily_price_backfill": "上市日線補齊",
  "market.tpex_daily_price_backfill": "上櫃日線補齊",
  "us_market.watchlist_daily_refresh": "美股自選日線補齊",
  "scheduler.us_market_daily_refresh": "排程美股日線補齊",
  "us_market.watchlist_resource_refresh": "美股自選資料補齊",
  "us_market.daily_price_quality_repair": "美股日線品質修復",
};

type JobMarketFilter = "all" | "tw" | "us";

const NON_RETRYABLE_JOB_TYPES = new Set(["market.tw_futures_quote_refresh"]);

const JOB_PANEL_TEXT: Record<
  JobMarketFilter,
  { subtitle: string; empty: string }
> = {
  all: {
    subtitle: "顯示最近 20 筆補資料與排程工作",
    empty: "尚無背景工作",
  },
  tw: {
    subtitle: "顯示最近 20 筆台股補資料與排程工作",
    empty: "尚無台股背景工作",
  },
  us: {
    subtitle: "顯示最近 20 筆美股補資料與排程工作",
    empty: "尚無美股背景工作",
  },
};

function getJobMarket(jobType: string): "tw" | "us" | "other" {
  if (jobType.startsWith("us_market.") || jobType === "scheduler.us_market_daily_refresh") {
    return "us";
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

function canRetry(job: JobRunRead) {
  const effectiveStatus = getEffectiveStatus(job);
  return (
    !NON_RETRYABLE_JOB_TYPES.has(job.job_type) &&
    (effectiveStatus === "error" || effectiveStatus === "partial_success")
  );
}

function buildStatusSummary(activeCount: number, failedCount: number) {
  if (activeCount > 0) {
    return {
      className: "omi-job-status-pill-active",
      label: `同步中 ${activeCount}`,
    };
  }

  if (failedCount > 0) {
    return {
      className: "omi-job-status-pill-attention",
      label: `待確認 ${failedCount}`,
    };
  }

  return {
    className: "omi-job-status-pill-idle",
    label: "正常",
  };
}

function formatShortText(value: string | null, maxLength = 220) {
  if (!value) return null;

  return value.length > maxLength ? `${value.slice(0, maxLength).trimEnd()}...` : value;
}

function formatResultSummary(job: JobRunRead) {
  const requestedCount = getFirstResultNumber(job, [
    "requested_count",
    "requested_stock_count",
    "requested_symbol_count",
    "symbol_count",
    "total_count",
  ]);
  const successCount = getFirstResultNumber(job, ["success_count", "current_count"]);
  const warningCount = getFirstResultNumber(job, ["warning_count"]);
  const errorCount =
    getFirstResultNumber(job, ["error_count", "failed_count"]) ??
    getResultErrors(job).length;
  const insertedCount = getFirstResultNumber(job, ["inserted_count"]);
  const updatedCount = getFirstResultNumber(job, ["updated_count"]);
  const fetchedCount = getFirstResultNumber(job, ["fetched_count"]);
  const skippedExistingCount = getFirstResultNumber(job, [
    "skipped_existing_count",
    "skipped_count",
  ]);
  const parts: string[] = [];

  if (requestedCount !== null && errorCount !== null) {
    parts.push(`完成 ${Math.max(requestedCount - errorCount, 0)}/${requestedCount}`);
  } else if (requestedCount !== null && successCount !== null) {
    parts.push(`完成 ${successCount}/${requestedCount}`);
  }

  if (insertedCount !== null && insertedCount > 0) parts.push(`新增 ${insertedCount}`);
  if (updatedCount !== null && updatedCount > 0) parts.push(`更新 ${updatedCount}`);
  if (fetchedCount !== null && fetchedCount > 0) parts.push(`取得 ${fetchedCount}`);
  if (skippedExistingCount !== null && skippedExistingCount > 0) {
    parts.push(`已存在 ${skippedExistingCount}`);
  }
  if (warningCount !== null && warningCount > 0) parts.push(`警告 ${warningCount}`);
  if (errorCount !== null && errorCount > 0) parts.push(`失敗 ${errorCount}`);

  return parts;
}

function formatResultItemTitle(row: Record<string, unknown>) {
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
      : sourceName ?? category ?? "項目";

  return tradeDate ? `${title} · ${tradeDate}` : title;
}

function formatResultItemMessage(row: Record<string, unknown>) {
  return (
    getResultString(row.error_message) ??
    getResultString(row.message) ??
    getResultString(row.status) ??
    "補資料未完成"
  );
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
  const summaryParts = formatResultSummary(job);
  const failedItems = getFailedResultItems(job);
  const visibleFailedItems = failedItems.slice(0, 4);
  const errorMessage = formatShortText(job.error_message);

  return (
    <div className="border-t border-omi-border-subtle px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-omi-text">
            {getJobTypeLabel(job.job_type)}
            {job.target ? <span className="ml-1 text-omi-text-muted">#{job.target}</span> : null}
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">{formatJobStatus(job)}</div>
        </div>
        <span className={`shrink-0 border px-2 py-1 text-[11px] font-bold ${statusTone(job)}`}>
          {getEffectiveStatus(job)}
        </span>
      </div>

      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-omi-text-muted">
        <span>更新 {formatDateTime(job.updated_at)}</span>
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
            <div key={`${formatResultItemTitle(row)}-${index}`} className="border border-omi-danger-border bg-omi-danger-soft px-2 py-1 text-xs text-omi-danger">
              <div className="font-bold">{formatResultItemTitle(row)}</div>
              <div className="mt-0.5 break-words text-[11px]">
                {formatShortText(formatResultItemMessage(row))}
              </div>
            </div>
          ))}
          {failedItems.length > visibleFailedItems.length ? (
            <div className="text-[11px] text-omi-text-muted">
              還有 {failedItems.length - visibleFailedItems.length} 筆失敗項目
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
          {retryingJobId === job.id ? "重新排程中" : "重新排程"}
        </button>
      ) : null}
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
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<JobRunRead[]>([]);
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
      setErrorMessage(error instanceof Error ? error.message : "工作狀態讀取失敗");
    }
  }, [market]);

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
  const panelText = JOB_PANEL_TEXT[market];
  const failedCount = useMemo(
    () =>
      jobs.filter((job) => {
        const effectiveStatus = getEffectiveStatus(job);
        return effectiveStatus === "error" || effectiveStatus === "partial_success";
      }).length,
    [jobs]
  );
  const statusSummary = useMemo(
    () => buildStatusSummary(activeCount, failedCount),
    [activeCount, failedCount]
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
          "flex min-w-[104px] items-center justify-between gap-2 border border-omi-border bg-omi-surface px-3 py-2 text-sm font-bold text-omi-text shadow-sm hover:border-omi-border-strong",
          inline ? "w-full" : "",
        ].join(" ")}
        onClick={() => setOpen((value) => !value)}
      >
        <span>更新狀態</span>
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
              <h2 className="text-sm font-black text-omi-text-strong">背景工作</h2>
              <p className="text-xs text-omi-text-muted">{panelText.subtitle}</p>
            </div>
            <button
              type="button"
              className="h-7 shrink-0 whitespace-nowrap border border-omi-border px-2 text-[11px] font-bold text-omi-text hover:border-omi-border-strong"
              onClick={() => void loadJobs()}
            >
              重整
            </button>
          </div>

          {errorMessage ? (
            <div className="border-b border-omi-danger-border bg-omi-danger-soft px-3 py-2 text-xs text-omi-danger">
              {errorMessage}
            </div>
          ) : null}

          <div className={inline ? "max-h-72 overflow-y-auto" : "max-h-[520px] overflow-y-auto"}>
            {jobs.length ? (
              jobs.map((job) => (
                <JobRow key={job.id} job={job} retryingJobId={retryingJobId} onRetry={handleRetry} />
              ))
            ) : (
              <div className="px-3 py-8 text-center text-sm text-omi-text-muted">
                {panelText.empty}
              </div>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}

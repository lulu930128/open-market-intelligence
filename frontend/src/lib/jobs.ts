import { fetchJson, requestJson } from "@/lib/api";
import type { TranslationFunction } from "@/i18n";
import type { JobRunRead } from "@/types/market";

const TERMINAL_STATUSES = new Set(["success", "error"]);

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function isJobTerminal(job: JobRunRead) {
  return TERMINAL_STATUSES.has(job.status);
}

function getJobResultObject(job: JobRunRead) {
  const result = job.result;

  if (!result || typeof result !== "object" || Array.isArray(result)) {
    return null;
  }

  return result as Record<string, unknown>;
}

export function getJobResultStatus(job: JobRunRead) {
  const status = getJobResultObject(job)?.status;

  return typeof status === "string" ? status : null;
}

function fallbackInterpolate(message: string, values: Record<string, string | number>) {
  return message.replace(/\{(\w+)\}/g, (match, key) => {
    const value = values[key];
    return value === undefined ? match : String(value);
  });
}

function text(
  t: TranslationFunction | undefined,
  key: string,
  fallback: string,
  values: Record<string, string | number> = {}
) {
  return t ? t(key, values) : fallbackInterpolate(fallback, values);
}

function getJobResultMessage(job: JobRunRead, t?: TranslationFunction) {
  const result = getJobResultObject(job);
  const message = result?.message;

  if (typeof message === "string" && message) {
    return message;
  }

  const errorCount = result?.error_count;

  if (typeof errorCount === "number" && errorCount > 0) {
    return text(t, "jobs.result.failedSources", "{count} sources failed", {
      count: errorCount,
    });
  }

  return null;
}

export function formatJobStatus(job: JobRunRead, t?: TranslationFunction) {
  const total = Math.max(job.progress_total || 1, 1);
  const current = Math.min(Math.max(job.progress_current || 0, 0), total);
  const resultStatus = getJobResultStatus(job);
  const effectiveStatus = job.status === "success" && resultStatus ? resultStatus : job.status;
  const label =
    t?.(`jobs.status.${effectiveStatus}`) ??
    {
      queued: "Queued",
      running: "Backfilling",
      success: "Backfill complete",
      partial_success: "Partially complete",
      skipped: "No backfill needed",
      error: "Backfill failed",
    }[effectiveStatus] ??
    effectiveStatus;
  const message = job.error_message || getJobResultMessage(job, t) || job.message;

  return `${label} (${current}/${total})${message ? `：${message}` : ""}`;
}

export async function pollJobUntilComplete(
  jobId: number,
  options?: {
    intervalMs?: number;
    timeoutMs?: number;
    onUpdate?: (job: JobRunRead) => void;
  }
) {
  const intervalMs = options?.intervalMs ?? 1000;
  const timeoutMs = options?.timeoutMs ?? 600000;
  const deadline = Date.now() + timeoutMs;

  let job = await fetchJson<JobRunRead>(`/api/jobs/${jobId}`);
  options?.onUpdate?.(job);

  while (!isJobTerminal(job)) {
    if (Date.now() >= deadline) {
      throw new Error(`Backfill job ${jobId} timed out.`);
    }

    await sleep(intervalMs);
    job = await fetchJson<JobRunRead>(`/api/jobs/${jobId}`);
    options?.onUpdate?.(job);
  }

  if (job.status === "error") {
    throw new Error(job.error_message || job.message || `Backfill job ${jobId} failed.`);
  }

  return job;
}

export async function requestBackfillJob(
  path: string,
  options: RequestInit,
  params?: Record<string, string | number | boolean>,
  pollOptions?: {
    intervalMs?: number;
    timeoutMs?: number;
    onUpdate?: (job: JobRunRead) => void;
  }
) {
  const queuedJob = await requestJson<JobRunRead>(path, options, params);
  pollOptions?.onUpdate?.(queuedJob);
  return pollJobUntilComplete(queuedJob.id, pollOptions);
}

export function getJobResult<T>(job: JobRunRead) {
  return (job.result ?? null) as T | null;
}

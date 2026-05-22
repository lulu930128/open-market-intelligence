import { fetchJson, requestJson } from "@/lib/api";
import type { JobRunRead } from "@/types/market";

const TERMINAL_STATUSES = new Set(["success", "error"]);

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function isJobTerminal(job: JobRunRead) {
  return TERMINAL_STATUSES.has(job.status);
}

export function formatJobStatus(job: JobRunRead) {
  const labels: Record<string, string> = {
    queued: "已排程",
    running: "補資料中",
    success: "補資料完成",
    error: "補資料失敗",
  };
  const total = Math.max(job.progress_total || 1, 1);
  const current = Math.min(Math.max(job.progress_current || 0, 0), total);
  const label = labels[job.status] ?? job.status;
  const message = job.error_message || job.message;

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

import { randomUUID } from "node:crypto";

import { getApiProxyTarget } from "@/lib/serverApiConfig";
import type { BackendConnectionIssueCode } from "@/types/runtime";

const DEFAULT_SERVER_GET_TIMEOUT_MS = 20_000;
const DEFAULT_SERVER_MUTATION_TIMEOUT_MS = 120_000;
const apiProxyTarget = getApiProxyTarget();

type ServerBackendErrorKind = "timeout" | "network" | "http" | "invalid_response";

export class ServerBackendError extends Error {
  readonly kind: ServerBackendErrorKind;
  readonly path: string;
  readonly status: number | null;
  readonly requestId: string | null;

  constructor({
    kind,
    message,
    path,
    status = null,
    requestId = null,
  }: {
    kind: ServerBackendErrorKind;
    message: string;
    path: string;
    status?: number | null;
    requestId?: string | null;
  }) {
    super(message);
    this.name = "ServerBackendError";
    this.kind = kind;
    this.path = path;
    this.status = status;
    this.requestId = requestId;
  }
}

export function backendConnectionIssueCode(error: unknown): BackendConnectionIssueCode {
  if (!(error instanceof ServerBackendError)) return "unavailable";
  if (error.kind === "timeout") return "timeout";
  if (error.kind === "invalid_response") return "invalid_response";
  if (error.kind === "http") return "request_failed";
  return "unavailable";
}

function requestTimeoutMs(init: RequestInit, configuredTimeoutMs: number | undefined) {
  if (configuredTimeoutMs !== undefined) return configuredTimeoutMs;
  const method = init.method?.toUpperCase() ?? "GET";
  return method === "GET" || method === "HEAD"
    ? DEFAULT_SERVER_GET_TIMEOUT_MS
    : DEFAULT_SERVER_MUTATION_TIMEOUT_MS;
}

async function readBackendError(response: Response) {
  const text = await response.text();
  const responseRequestId = response.headers.get("x-request-id");

  if (!text) {
    return {
      message: response.statusText || "Backend request failed.",
      requestId: responseRequestId,
    };
  }

  try {
    const payload = JSON.parse(text) as {
      error?: { message?: string; request_id?: string | null };
      detail?: string;
    };
    const message = payload.error?.message || payload.detail || text;
    const requestId = payload.error?.request_id || responseRequestId;
    return {
      message: requestId ? `${message} (request ${requestId})` : message,
      requestId,
    };
  } catch {
    return { message: text, requestId: responseRequestId };
  }
}

export async function fetchServerBackendJson<T>(
  path: string,
  init: RequestInit = {},
  options: { timeoutMs?: number } = {}
): Promise<T> {
  const timeoutMs = requestTimeoutMs(init, options.timeoutMs);
  const controller = new AbortController();
  const externalSignal = init.signal ?? null;
  let timedOut = false;
  const timeoutId =
    timeoutMs > 0
      ? setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, timeoutMs)
      : null;
  const abortFromExternal = () => controller.abort();

  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", abortFromExternal, { once: true });
  }

  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (!headers.has("x-request-id")) headers.set("x-request-id", randomUUID());
  const requestId = headers.get("x-request-id");

  let response: Response;
  try {
    response = await fetch(`${apiProxyTarget}${path}`, {
      ...init,
      headers,
      cache: init.cache ?? "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut) {
      throw new ServerBackendError({
        kind: "timeout",
        message: `Backend timeout after ${timeoutMs}ms: ${path}`,
        path,
        requestId,
      });
    }
    if (externalSignal?.aborted) throw error;
    throw new ServerBackendError({
      kind: "network",
      message: error instanceof Error ? error.message : `Backend unavailable: ${path}`,
      path,
      requestId,
    });
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
    if (externalSignal) externalSignal.removeEventListener("abort", abortFromExternal);
  }

  if (!response.ok) {
    const detail = await readBackendError(response);
    throw new ServerBackendError({
      kind: "http",
      message: `Backend ${response.status}: ${detail.message}`,
      path,
      status: response.status,
      requestId: detail.requestId,
    });
  }

  if (response.status === 204) return null as T;

  try {
    return (await response.json()) as T;
  } catch {
    throw new ServerBackendError({
      kind: "invalid_response",
      message: `Backend returned invalid JSON: ${path}`,
      path,
      status: response.status,
      requestId: response.headers.get("x-request-id") || requestId,
    });
  }
}

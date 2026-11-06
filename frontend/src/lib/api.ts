const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || undefined;
const API_PROXY_PATH =
  process.env.NEXT_PUBLIC_API_PROXY_PATH?.trim() || "/omi-data";

function buildSameOriginPath(path: string) {
  if (path.startsWith("/api/watchlists")) {
    return path.replace(/^\/api\/watchlists(?=\/|$)/, `${API_PROXY_PATH}/wl`);
  }

  return path.replace(/^\/api(?=\/|$)/, API_PROXY_PATH);
}

type ApiParams = Record<string, string | number | boolean>;

export type ApiErrorKind = "timeout" | "network" | "http" | "invalid_response";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly path: string;
  readonly status: number | null;
  readonly code: string | null;
  readonly requestId: string | null;

  constructor({
    kind,
    message,
    path,
    status = null,
    code = null,
    requestId = null,
  }: {
    kind: ApiErrorKind;
    message: string;
    path: string;
    status?: number | null;
    code?: string | null;
    requestId?: string | null;
  }) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.path = path;
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export type ApiRequestOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
};

export function requireJsonArray<T>(
  payload: unknown,
  label: string,
  isItem?: (value: unknown) => value is T
): T[] {
  if (!Array.isArray(payload) || (isItem && !payload.every(isItem))) {
    throw new Error(`${label}資料格式錯誤，請重新整理。`);
  }

  return payload as T[];
}

const DEFAULT_GET_TIMEOUT_MS = 20_000;
const DEFAULT_MUTATION_TIMEOUT_MS = 120_000;

export function createApiRequestId() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }

  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function withRequestContext(headers: HeadersInit | undefined) {
  const requestHeaders = new Headers(headers);
  if (!requestHeaders.has("x-request-id")) {
    requestHeaders.set("x-request-id", createApiRequestId());
  }
  return requestHeaders;
}

export function buildApiUrl(path: string, params?: ApiParams) {
  const sameOriginPath = buildSameOriginPath(path);
  const url = API_BASE_URL
    ? new URL(path, API_BASE_URL)
    : new URL(sameOriginPath, window.location.origin);

  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      url.searchParams.set(key, String(value));
    });
  }

  return url.toString();
}

async function fetchWithOptionalTimeout<T>(
  path: string,
  params: ApiParams | undefined,
  init: RequestInit,
  options: ApiRequestOptions | undefined,
  defaultTimeoutMs: number,
  consumeResponse: (response: Response) => Promise<T>
): Promise<T> {
  const timeoutMs = options?.timeoutMs ?? defaultTimeoutMs;
  const externalSignal = options?.signal ?? init.signal ?? null;
  const requestHeaders = withRequestContext(init.headers);
  const requestId = requestHeaders.get("x-request-id");
  const requestInit = {
    ...init,
    headers: requestHeaders,
  };

  const controller = new AbortController();
  let timedOut = false;
  const timeoutId =
    timeoutMs > 0
      ? setTimeout(() => {
          if (controller.signal.aborted) return;
          timedOut = true;
          controller.abort();
        }, timeoutMs)
      : null;
  const abortFromExternal = () => controller.abort();

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", abortFromExternal, { once: true });
    }
  }

  try {
    const response = await fetch(buildApiUrl(path, params), {
      ...requestInit,
      signal: controller.signal,
    });
    // Headers do not complete a request. Keep the deadline and external abort
    // listener alive through both success JSON and HTTP error-body consumption.
    return await consumeResponse(response);
  } catch (error) {
    if (timedOut) {
      throw new ApiError({
        kind: "timeout",
        message: `API timeout after ${timeoutMs}ms: ${path}`,
        path,
        requestId,
      });
    }
    if (externalSignal?.aborted) {
      throw error;
    }
    if (error instanceof ApiError) throw error;
    throw new ApiError({
      kind: "network",
      message: error instanceof Error ? error.message : `API network error: ${path}`,
      path,
      requestId,
    });
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    if (externalSignal) {
      externalSignal.removeEventListener("abort", abortFromExternal);
    }
  }
}

async function readApiError(response: Response) {
  const text = await response.text();
  const responseRequestId = response.headers.get("x-request-id");

  if (!text) {
    return {
      message: response.statusText || "Request failed.",
      code: null,
      requestId: responseRequestId,
    };
  }

  try {
    const payload = JSON.parse(text) as {
      error?: {
        message?: string;
        code?: string;
        request_id?: string | null;
      };
      detail?: string;
    };
    const message = payload.error?.message || payload.detail || text;
    const requestId = payload.error?.request_id || responseRequestId;

    return {
      message: requestId ? `${message} (request ${requestId})` : message,
      code: payload.error?.code ?? null,
      requestId,
    };
  } catch {
    return {
      message: text,
      code: null,
      requestId: responseRequestId,
    };
  }
}

export async function createHttpApiError(response: Response, path: string) {
  const detail = await readApiError(response);
  return new ApiError({
    kind: "http",
    message: `API ${response.status}: ${detail.message}`,
    path,
    status: response.status,
    code: detail.code,
    requestId: detail.requestId,
  });
}

async function readJsonResponse<T>(response: Response, path: string): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch (error) {
    // A truncated/disconnected body or abort is a transport failure, not JSON.
    if (!(error instanceof SyntaxError)) throw error;
    throw new ApiError({
      kind: "invalid_response",
      message: `API returned invalid JSON: ${path}`,
      path,
      status: response.status,
      requestId: response.headers.get("x-request-id"),
    });
  }
}

export async function fetchJson<T>(
  path: string,
  params?: ApiParams,
  options?: ApiRequestOptions
): Promise<T> {
  return fetchWithOptionalTimeout(
    path,
    params,
    {
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
    options,
    DEFAULT_GET_TIMEOUT_MS,
    async (response) => {
      if (!response.ok) throw await createHttpApiError(response, path);
      return readJsonResponse<T>(response, path);
    }
  );
}

export async function requestJson<T>(
  path: string,
  options: RequestInit,
  params?: ApiParams,
  apiOptions?: ApiRequestOptions
): Promise<T> {
  return fetchWithOptionalTimeout(
    path,
    params,
    {
      ...options,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(options.headers ?? {}),
      },
      cache: "no-store",
    },
    apiOptions,
    DEFAULT_MUTATION_TIMEOUT_MS,
    async (response) => {
      if (!response.ok) throw await createHttpApiError(response, path);
      if (response.status === 204) return null as T;
      return readJsonResponse<T>(response, path);
    }
  );
}

export async function deleteRequest(
  path: string,
  params?: ApiParams,
  options?: ApiRequestOptions
): Promise<void> {
  return fetchWithOptionalTimeout(
    path,
    params,
    {
      method: "DELETE",
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
    options,
    DEFAULT_GET_TIMEOUT_MS,
    async (response) => {
      if (!response.ok) throw await createHttpApiError(response, path);
    }
  );
}

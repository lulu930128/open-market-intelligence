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

async function fetchWithOptionalTimeout(
  path: string,
  params: ApiParams | undefined,
  init: RequestInit,
  options: ApiRequestOptions | undefined,
  defaultTimeoutMs: number
) {
  const timeoutMs = options?.timeoutMs ?? defaultTimeoutMs;
  const externalSignal = options?.signal ?? init.signal ?? null;

  if (timeoutMs <= 0 && !externalSignal) {
    return fetch(buildApiUrl(path, params), init);
  }

  const controller = new AbortController();
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
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", abortFromExternal, { once: true });
    }
  }

  try {
    return await fetch(buildApiUrl(path, params), {
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut) {
      throw new Error(`API timeout after ${timeoutMs}ms: ${path}`);
    }
    throw error;
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

  if (!text) {
    return response.statusText || "Request failed.";
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
    const requestId = payload.error?.request_id;

    return requestId ? `${message} (request ${requestId})` : message;
  } catch {
    return text;
  }
}

export async function fetchJson<T>(
  path: string,
  params?: ApiParams,
  options?: ApiRequestOptions
): Promise<T> {
  const response = await fetchWithOptionalTimeout(
    path,
    params,
    {
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
    options,
    DEFAULT_GET_TIMEOUT_MS
  );

  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await readApiError(response)}`);
  }

  return response.json() as Promise<T>;
}

export async function requestJson<T>(
  path: string,
  options: RequestInit,
  params?: ApiParams,
  apiOptions?: ApiRequestOptions
): Promise<T> {
  const response = await fetchWithOptionalTimeout(
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
    0
  );

  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await readApiError(response)}`);
  }

  if (response.status === 204) {
    return null as T;
  }

  return response.json() as Promise<T>;
}

export async function deleteRequest(
  path: string,
  params?: ApiParams,
  options?: ApiRequestOptions
): Promise<void> {
  const response = await fetchWithOptionalTimeout(
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
    DEFAULT_GET_TIMEOUT_MS
  );

  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await readApiError(response)}`);
  }
}

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

export function buildApiUrl(path: string, params?: Record<string, string | number | boolean>) {
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

export async function fetchJson<T>(
  path: string,
  params?: Record<string, string | number | boolean>
): Promise<T> {
  const response = await fetch(buildApiUrl(path, params), {
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text}`);
  }

  return response.json() as Promise<T>;
}

export async function requestJson<T>(
  path: string,
  options: RequestInit,
  params?: Record<string, string | number | boolean>
): Promise<T> {
  const response = await fetch(buildApiUrl(path, params), {
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text}`);
  }

  if (response.status === 204) {
    return null as T;
  }

  return response.json() as Promise<T>;
}

export async function deleteRequest(
  path: string,
  params?: Record<string, string | number | boolean>
): Promise<void> {
  const response = await fetch(buildApiUrl(path, params), {
    method: "DELETE",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text}`);
  }
}

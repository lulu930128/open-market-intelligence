const DEFAULT_API_PROXY_PATH = "/omi-data";
const DEFAULT_BACKEND_HOST = "127.0.0.1";
const DEFAULT_BACKEND_PORT = "8400";

type EnvSource = Record<string, string | undefined>;

function cleanEnvValue(value: string | undefined) {
  const cleaned = value?.trim();
  return cleaned || undefined;
}

function trimTrailingSlashes(value: string) {
  return value.replace(/\/+$/, "");
}

function formatUrlHost(host: string) {
  if (host.includes(":") && !host.startsWith("[") && !host.endsWith("]")) {
    return `[${host}]`;
  }

  return host;
}

export function getApiProxyPath(env: EnvSource = process.env) {
  const configuredPath =
    cleanEnvValue(env.API_PROXY_PATH) ||
    cleanEnvValue(env.NEXT_PUBLIC_API_PROXY_PATH) ||
    DEFAULT_API_PROXY_PATH;

  return configuredPath.startsWith("/") ? configuredPath : `/${configuredPath}`;
}

export function getApiProxyTarget(env: EnvSource = process.env) {
  const configuredTarget = cleanEnvValue(env.API_PROXY_TARGET);
  if (configuredTarget) {
    return trimTrailingSlashes(configuredTarget);
  }

  const host =
    cleanEnvValue(env.OMI_BACKEND_HOST) ||
    cleanEnvValue(env.APP_HOST) ||
    DEFAULT_BACKEND_HOST;
  const port =
    cleanEnvValue(env.OMI_BACKEND_PORT) ||
    cleanEnvValue(env.APP_PORT) ||
    DEFAULT_BACKEND_PORT;

  return `http://${formatUrlHost(host)}:${port}`;
}

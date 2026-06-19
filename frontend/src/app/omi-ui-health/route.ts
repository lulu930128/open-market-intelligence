import { NextResponse } from "next/server";

import { getApiProxyPath, getApiProxyTarget } from "@/lib/serverApiConfig";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({
    status: "ok",
    app_name: "Open Market Intelligence",
    component: "frontend",
    runtime: {
      frontend_dir: process.cwd(),
      node_version: process.version,
      hostname: process.env.HOSTNAME ?? null,
      port: process.env.PORT ?? null,
      api_proxy_path: getApiProxyPath(),
      api_proxy_target: getApiProxyTarget(),
    },
  });
}

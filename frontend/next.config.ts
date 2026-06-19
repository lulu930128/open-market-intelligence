import type { NextConfig } from "next";

import { getApiProxyPath, getApiProxyTarget } from "./src/lib/serverApiConfig";

const apiProxyTarget = getApiProxyTarget();
const apiProxyPath = getApiProxyPath();

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  output: "standalone",
  async rewrites() {
    return [
      {
        source: `${apiProxyPath}/wl/:path*`,
        destination: `${apiProxyTarget}/api/watchlists/:path*`,
      },
      {
        source: `${apiProxyPath}/:path*`,
        destination: `${apiProxyTarget}/api/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${apiProxyTarget}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;

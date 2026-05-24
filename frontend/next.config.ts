import type { NextConfig } from "next";

const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8300";
const apiProxyPath = process.env.API_PROXY_PATH ?? "/omi-data";

const nextConfig: NextConfig = {
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

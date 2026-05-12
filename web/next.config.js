/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `standalone` emits a minimal `server.js` + pruned node_modules under
  // `.next/standalone/` — required for the production Docker image that
  // Render and similar PaaS deploys use.
  output: "standalone",
  experimental: {
    serverActions: { bodySizeLimit: "5mb" },
    // Next.js 15 auto-optimises a list of common icon packages with a
    // barrel loader. The loader can't resolve `react-icons/pi` subpath
    // exports correctly, so we force the default resolver instead.
    optimizePackageImports: [],
  },
  transpilePackages: [
    "@blocknote/core",
    "@blocknote/react",
    "@blocknote/mantine",
    "@blocknote/server-util",
  ],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=()",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;

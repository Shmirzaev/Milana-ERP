/** @type {import('next').NextConfig} */
const defaultApiUrl =
  process.env.NODE_ENV === "production"
    ? "https://shmirzaev-milana-erp-api.hf.space"
    : "http://localhost:8000";
const envApiUrl = process.env.NEXT_PUBLIC_API_URL || process.env.API_URL || "";
const normalizedRawApiUrl = String(envApiUrl || "").trim() || defaultApiUrl;
const withScheme = /^https?:\/\//i.test(normalizedRawApiUrl) ? normalizedRawApiUrl : `http://${normalizedRawApiUrl}`;
const apiBaseUrl = withScheme.replace(/\/+$/, "");

const nextConfig = {
  reactStrictMode: true,
  async redirects() {
    return [
      {
        source: "/warehouse",
        destination: "/warehouse-map",
        permanent: false,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiBaseUrl}/api/:path*`,
      },
      {
        source: "/storage/:path*",
        destination: `${apiBaseUrl}/storage/:path*`,
      },
      {
        source: "/health",
        destination: `${apiBaseUrl}/health`,
      },
    ];
  },
};
module.exports = nextConfig;

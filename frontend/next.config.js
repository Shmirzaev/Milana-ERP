/** @type {import('next').NextConfig} */
const defaultApiUrl =
  process.env.NODE_ENV === "production"
    ? "https://milana-erp.onrender.com"
    : "http://localhost:8000";
const envApiUrl = process.env.NEXT_PUBLIC_API_URL || process.env.API_URL || "";
const normalizedRawApiUrl = String(envApiUrl || "").trim() || defaultApiUrl;
const withScheme = /^https?:\/\//i.test(normalizedRawApiUrl) ? normalizedRawApiUrl : `http://${normalizedRawApiUrl}`;
const apiBaseUrl = withScheme.replace(/\/+$/, "");

const nextConfig = {
  reactStrictMode: true,
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
    ];
  },
};
module.exports = nextConfig;

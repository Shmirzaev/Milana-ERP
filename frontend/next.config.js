/** @type {import('next').NextConfig} */
const isProduction = process.env.NODE_ENV === "production";
const defaultApiUrl =
  isProduction
    ? "https://shmirzaev-milana-erp-api.hf.space"
    : "http://localhost:8000";
const envApiUrl = process.env.NEXT_PUBLIC_API_URL || process.env.API_URL || "";
const normalizedRawApiUrl = String(envApiUrl || "").trim() || defaultApiUrl;
const withScheme = /^https?:\/\//i.test(normalizedRawApiUrl) ? normalizedRawApiUrl : `http://${normalizedRawApiUrl}`;
const apiBaseUrl = withScheme.replace(/\/+$/, "");
const apiOrigin = (() => {
  try {
    return new URL(apiBaseUrl).origin;
  } catch {
    return "";
  }
})();
const connectSrc = ["'self'", apiOrigin].filter(Boolean).join(" ");
const scriptSrc = ["'self'", "'unsafe-inline'", ...(!isProduction ? ["'unsafe-eval'"] : [])].join(" ");
const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "base-uri 'self'",
      "object-src 'none'",
      "frame-ancestors 'none'",
      "form-action 'self'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      "style-src 'self' 'unsafe-inline'",
      `script-src ${scriptSrc}`,
      `connect-src ${connectSrc}`,
      ...(isProduction ? ["upgrade-insecure-requests"] : []),
    ].join("; "),
  },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
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

/** @type {import('next').NextConfig} */
const isProduction = process.env.NODE_ENV === "production";
const publicRawApiUrl = String(process.env.NEXT_PUBLIC_API_URL || "").trim();
const serverRawApiUrl = String(process.env.API_URL || "").trim();
const normalizedRawApiUrl = serverRawApiUrl || publicRawApiUrl;

if (isProduction && !normalizedRawApiUrl) {
  throw new Error(
    "Production frontend builds require NEXT_PUBLIC_API_URL or API_URL. Refusing to fall back to a hosted API.",
  );
}

const rawApiUrl = normalizedRawApiUrl || "http://localhost:8000";
const defaultScheme = isProduction ? "https" : "http";
function normalizeApiUrl(value, scheme = defaultScheme) {
  const withScheme = /^https?:\/\//i.test(value) ? value : `${scheme}://${value}`;
  return withScheme.replace(/\/+$/, "");
}
const apiBaseUrl = normalizeApiUrl(rawApiUrl);
const publicApiBaseUrl = publicRawApiUrl ? normalizeApiUrl(publicRawApiUrl) : apiBaseUrl;
if (isProduction && publicRawApiUrl && /^http:\/\//i.test(publicApiBaseUrl)) {
  throw new Error("Production frontend public API URL must use HTTPS.");
}
const apiOrigin = (() => {
  try {
    return new URL(publicApiBaseUrl).origin;
  } catch {
    throw new Error(`Invalid API URL configured for frontend: ${publicApiBaseUrl}`);
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
  // Production is promoted as one immutable artifact. The standalone output
  // contains only the runtime server and traced dependencies, so production
  // never needs npm install or next build on the serving VM.
  output: "standalone",
  reactStrictMode: true,
  experimental: {
    // The API accepts files up to 20 MB. Leave room for multipart framing so
    // oversized requests reach the API and receive a proper validation error.
    proxyClientMaxBodySize: "25mb",
  },
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

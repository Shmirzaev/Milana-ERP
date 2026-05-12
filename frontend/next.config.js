/** @type {import('next').NextConfig} */
const rawApiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const withScheme = /^https?:\/\//i.test(rawApiUrl) ? rawApiUrl : `http://${rawApiUrl}`;
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

type ContentSecurityPolicyOptions = {
  development?: boolean;
  connectOrigins?: string[];
};

const normalizedOrigin = (value: string): string | null => {
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
};

export function configuredBrowserConnectOrigins(): string[] {
  const configured = String(process.env.NEXT_PUBLIC_API_URL || "").trim();
  const origin = configured ? normalizedOrigin(configured) : null;
  return origin ? [origin] : [];
}

export function buildContentSecurityPolicy(
  nonce: string,
  options: ContentSecurityPolicyOptions = {},
): string {
  if (!/^[A-Za-z0-9_-]+$/.test(nonce)) {
    throw new Error("CSP nonce must contain only URL-safe base64 characters");
  }
  const development = options.development ?? process.env.NODE_ENV !== "production";
  const connectOrigins = [...new Set(options.connectOrigins || [])]
    .map(normalizedOrigin)
    .filter((origin): origin is string => Boolean(origin));
  const scriptSources = ["'self'", `'nonce-${nonce}'`, ...(development ? ["'unsafe-eval'"] : [])];
  const connectSources = ["'self'", ...connectOrigins];

  return [
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    // React uses style attributes throughout the application. Keeping styles
    // compatible does not require allowing inline script execution.
    "style-src 'self' 'unsafe-inline'",
    `script-src ${scriptSources.join(" ")}`,
    `connect-src ${connectSources.join(" ")}`,
    ...(development ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}

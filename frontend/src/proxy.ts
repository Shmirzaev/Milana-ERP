import { NextRequest, NextResponse } from "next/server";
import {
  buildContentSecurityPolicy,
  configuredBrowserConnectOrigins,
} from "@/lib/contentSecurityPolicy";

export function proxy(request: NextRequest) {
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const policy = buildContentSecurityPolicy(nonce, {
    connectOrigins: configuredBrowserConnectOrigins(),
  });
  const requestHeaders = new Headers(request.headers);
  // Next reads the request CSP and applies this nonce to its framework and
  // hydration scripts. The separate header lets the root layout nonce its
  // small theme bootstrap without exposing a reusable static allowance.
  requestHeaders.set("Content-Security-Policy", policy);
  requestHeaders.set("x-nonce", nonce);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Prefetch requests must receive the same nonce boundary as documents.
      source: "/((?!api|storage|health|_next/static|_next/image|favicon.ico).*)",
    },
  ],
};

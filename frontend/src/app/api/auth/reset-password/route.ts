import { NextResponse } from "next/server";

const LOCAL_API_URL = "http://localhost:8000";

function apiBaseUrl(): string {
  const isProduction = process.env.NODE_ENV === "production";
  const raw = String(process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "").trim();
  if (isProduction && !raw) {
    throw new Error("Password reset proxy requires API_URL or NEXT_PUBLIC_API_URL in production.");
  }
  const target = raw || LOCAL_API_URL;
  const defaultScheme = isProduction ? "https" : "http";
  const withScheme = /^https?:\/\//i.test(target) ? target : `${defaultScheme}://${target}`;
  const normalized = withScheme.replace(/\/+$/, "");
  if (isProduction && /^http:\/\//i.test(normalized)) {
    throw new Error("Password reset proxy API URL must use HTTPS in production.");
  }
  return normalized;
}

export async function POST(request: Request) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }

  try {
    const baseUrl = apiBaseUrl();
    const res = await fetch(`${baseUrl}/api/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });

    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = { detail: res.statusText || "Password reset failed" };
    }

    return NextResponse.json(body, { status: res.status });
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("Password reset proxy")) {
      return NextResponse.json({ detail: error.message }, { status: 500 });
    }
    return NextResponse.json(
      { detail: "Password reset service is unavailable" },
      { status: 503 },
    );
  }
}

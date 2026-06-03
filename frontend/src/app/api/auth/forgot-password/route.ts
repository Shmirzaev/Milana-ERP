import { NextResponse } from "next/server";

const DEFAULT_API_URL = "https://shmirzaev-milana-erp-api.hf.space";

function apiBaseUrl(): string {
  const raw = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
  const withScheme = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  return withScheme.replace(/\/+$/, "");
}

export async function POST(request: Request) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }

  try {
    const res = await fetch(`${apiBaseUrl()}/api/auth/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });

    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = { detail: res.statusText || "Password reset request failed" };
    }

    return NextResponse.json(body, { status: res.status });
  } catch {
    return NextResponse.json(
      { detail: "Password reset service is unavailable" },
      { status: 503 },
    );
  }
}

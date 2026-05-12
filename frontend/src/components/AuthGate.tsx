"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMe } from "@/lib/auth";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { me, error, loading, hasToken } = useMe();

  useEffect(() => {
    // Only redirect once we have *definitive* knowledge that there's no token.
    if (hasToken === false) router.replace("/login");
    if (error) {
      // Token rejected by the API (expired/invalid) -> drop it and bounce to login.
      if (typeof window !== "undefined") localStorage.removeItem("erp_token");
      router.replace("/login");
    }
  }, [hasToken, error, router]);

  // Still detecting localStorage, or token exists but /me hasn't responded yet -> spinner.
  if (hasToken === undefined || (hasToken && (loading || !me))) {
    return <div className="p-6 text-slate-500">Loading…</div>;
  }
  if (!hasToken) return null;
  return <>{children}</>;
}

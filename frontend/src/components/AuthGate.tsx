"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { me, error, loading, hasToken } = useMe();
  const { t } = useT();

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
    return <div className="p-6 text-slate-500">{t("common.loading")}</div>;
  }
  if (!hasToken) return null;
  return <>{children}</>;
}

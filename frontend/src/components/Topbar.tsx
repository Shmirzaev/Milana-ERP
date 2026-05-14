"use client";
import useSWR from "swr";
import { Globe2, LogOut, Search, Server, Settings, WifiOff } from "lucide-react";
import { useMe, logout } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import LangSwitcher from "@/components/LangSwitcher";
import NotificationBell from "@/components/NotificationBell";

export default function Topbar() {
  const { me } = useMe();
  const { t } = useT();
  const { data: health, error } = useSWR<{ status: string; app: string }>(
    "/health",
    (url: string) => fetch(url).then((r) => {
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    }),
    { refreshInterval: 30_000, revalidateOnFocus: false },
  );
  const connected = health?.status === "ok" && !error;

  return (
    <header className="sticky top-0 z-10 flex min-h-[56px] items-center justify-between gap-4 border-b border-[#e3dfd3] bg-[#fdfcf8]/95 px-5 py-2 backdrop-blur">
      <div className="flex min-w-0 items-center gap-3">
        <div className="text-sm text-[#8a8472]">
          {me?.department ? `${t("top.department")}: ${me.department}` : null}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="hidden h-8 w-[274px] items-center gap-2 rounded-md border border-[#e3dfd3] bg-[#f1efe8] px-3 text-sm text-[#8a8472] xl:flex">
          <Search className="h-4 w-4" />
          <span className="truncate">Search orders, bundles, models...</span>
          <span className="ml-auto rounded border border-[#ded9ca] bg-[#fdfcf8] px-1.5 py-0.5 text-[11px]">⌘ K</span>
        </div>
        <div
          className={`hidden items-center gap-2 rounded-full px-2.5 py-1 text-xs font-medium md:flex ${
            connected ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
          }`}
          title={connected ? health?.app : "Backend health check failed"}
        >
          {connected ? <Server className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
          {connected ? "Backend ready" : "Backend offline"}
        </div>
        <button className="icon-btn" title="Language"><Globe2 /></button>
        <LangSwitcher />
        <div className="relative">
          <NotificationBell />
        </div>
        <button className="icon-btn" title="Settings"><Settings /></button>
        <div className="hidden text-right text-sm sm:block">
          <div className="font-medium text-[#14110b]">{me?.name || "-"}</div>
          <div className="text-xs text-[#8a8472]">{me?.role || ""}</div>
        </div>
        <button className="btn" onClick={() => logout()}>
          <LogOut className="h-4 w-4" />
          {t("auth.logout")}
        </button>
      </div>
    </header>
  );
}

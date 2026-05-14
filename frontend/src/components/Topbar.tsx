"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Globe2, LogOut, Search, Settings } from "lucide-react";
import { useMe, logout } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import LangSwitcher from "@/components/LangSwitcher";
import NotificationBell from "@/components/NotificationBell";

export default function Topbar() {
  const router = useRouter();
  const { me } = useMe();
  const { t } = useT();
  const [search, setSearch] = useState("");

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = search.trim();
    if (!q) return;
    router.push(`/sales-orders?q=${encodeURIComponent(q)}`);
  }

  return (
    <header className="sticky top-0 z-10 flex min-h-[56px] items-center justify-between gap-4 border-b border-[#e3dfd3] bg-[#fdfcf8]/95 px-5 py-2 backdrop-blur">
      <div className="flex min-w-0 items-center gap-3">
        <div className="text-sm text-[#8a8472]">
          {me?.department ? `${t("top.department")}: ${me.department}` : null}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <form onSubmit={submitSearch} className="hidden h-8 w-[274px] items-center gap-2 rounded-md border border-[#e3dfd3] bg-[#f1efe8] px-3 text-sm text-[#8a8472] xl:flex">
          <Search className="h-4 w-4" />
          <input
            className="w-full bg-transparent text-sm text-[#2c2920] placeholder:text-[#8a8472] focus:outline-none"
            placeholder={t("top.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="submit" className="rounded border border-[#ded9ca] bg-[#fdfcf8] px-1.5 py-0.5 text-[11px]">{t("top.searchSubmit")}</button>
        </form>
        <button className="icon-btn" title={t("top.language")}><Globe2 /></button>
        <LangSwitcher />
        <div className="relative">
          <NotificationBell />
        </div>
        <button className="icon-btn" title={t("common.actions")}><Settings /></button>
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


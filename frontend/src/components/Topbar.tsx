"use client";
import { useState } from "react";
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LogOut, Search, Settings } from "lucide-react";
import { useMe, logout } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import LangSwitcher from "@/components/LangSwitcher";
import NotificationBell from "@/components/NotificationBell";

export default function Topbar() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { me } = useMe();
  const { t, lang } = useT();
  const [search, setSearch] = useState("");
  const [now, setNow] = useState<Date>(new Date());

  useEffect(() => {
    setSearch(searchParams.get("q") ?? "");
  }, [searchParams]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const localeByLang: Record<string, string> = {
    en: "en-US",
    ru: "ru-RU",
    uz: "uz-UZ",
  };
  const locale = localeByLang[lang] || "en-US";
  const localDate = now.toLocaleDateString(locale, {
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const localTime = now.toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const tzName = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = search.trim();
    if (!q) return;

    const params = new URLSearchParams();
    params.set("q", q);
    router.push(`/search?${params.toString()}`);
  }

  return (
    <header className="sticky top-0 z-10 flex h-20 items-center justify-between gap-4 border-b border-[#e3dfd3] bg-[#fdfcf8]/95 px-5 backdrop-blur">
      <div className="flex min-w-0 items-center gap-3">
        <div className="text-sm text-[#8a8472]">
          {me?.department ? `${t("top.department")}: ${me.department}` : null}
        </div>
      </div>
      <div className="flex h-full items-center gap-3">
        <div className="hidden h-16 min-w-[180px] rounded-md border border-[#e3dfd3] bg-[#f8f6ef] px-3 text-right sm:flex sm:flex-col sm:justify-center">
          <div className="text-[10px] uppercase tracking-wide text-[#8a8472]">{t("top.localTime")}</div>
          <div className="text-[11px] font-medium leading-tight text-[#2c2920] whitespace-nowrap">{localDate}</div>
          <div className="text-[11px] font-semibold leading-tight text-[#14110b] whitespace-nowrap">{localTime}</div>
          <div className="text-[10px] leading-tight text-[#8a8472] whitespace-nowrap">{tzName}</div>
        </div>
        <form onSubmit={submitSearch} className="hidden h-10 w-[290px] items-center gap-2 rounded-md border border-[#e3dfd3] bg-[#f1efe8] px-3 text-sm text-[#8a8472] xl:flex">
          <Search className="h-4 w-4" />
          <input
            className="w-full bg-transparent text-sm text-[#2c2920] placeholder:text-[#8a8472] focus:outline-none"
            placeholder={t("top.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="submit" className="rounded border border-[#ded9ca] bg-[#fdfcf8] px-1.5 py-0.5 text-[11px]">{t("top.searchSubmit")}</button>
        </form>
        <LangSwitcher />
        <div className="relative">
          <NotificationBell />
        </div>
        <button className="icon-btn" title="Settings" onClick={() => router.push("/settings")}><Settings /></button>
        <button className="hidden text-right text-sm sm:block" onClick={() => router.push("/profile")} title="Profile">
          <div className="font-medium text-[#14110b]">{me?.name || "-"}</div>
          <div className="text-xs text-[#8a8472]">{me?.role || ""}</div>
        </button>
        <button className="btn" onClick={() => logout()}>
          <LogOut className="h-4 w-4" />
          {t("auth.logout")}
        </button>
      </div>
    </header>
  );
}


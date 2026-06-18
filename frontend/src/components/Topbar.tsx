"use client";
import { useEffect, useState } from "react";
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
    <header className="relative z-20 flex min-h-14 flex-wrap items-center justify-between gap-2 border-b border-[#e3dfd3] bg-[#fdfcf8]/95 px-3 py-2 backdrop-blur sm:gap-3 sm:px-4 lg:sticky lg:top-0 lg:min-h-20 lg:px-5">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <div className="truncate text-xs text-[#8a8472] sm:text-sm">
          {me?.department ? `${t("top.department")}: ${me.department}` : null}
        </div>
      </div>
      <form onSubmit={submitSearch} className="order-3 flex h-10 w-full items-center gap-2 rounded-md border border-[#e3dfd3] bg-[#f1efe8] px-3 text-sm text-[#8a8472] md:order-none md:w-[320px] xl:w-[360px]">
        <Search className="h-4 w-4 shrink-0" />
        <input
          className="min-w-0 flex-1 bg-transparent text-sm text-[#2c2920] placeholder:text-[#8a8472] focus:outline-none"
          placeholder={t("top.searchPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label={t("common.search")}
        />
        <button type="submit" className="shrink-0 rounded border border-[#ded9ca] bg-[#fdfcf8] px-2 py-1 text-[11px] font-medium text-[#3b3528]">{t("top.searchSubmit")}</button>
      </form>
      <div className="flex min-w-0 items-center justify-end gap-1.5 sm:gap-2 lg:h-full lg:gap-3">
        <div className="hidden h-16 min-w-[180px] rounded-md border border-[#e3dfd3] bg-[#f8f6ef] px-3 text-right xl:flex xl:flex-col xl:justify-center">
          <div className="text-[10px] uppercase tracking-wide text-[#8a8472]">{t("top.localTime")}</div>
          <div className="text-[11px] font-medium leading-tight text-[#2c2920] whitespace-nowrap">{localDate}</div>
          <div className="text-[11px] font-semibold leading-tight text-[#14110b] whitespace-nowrap">{localTime}</div>
          <div className="text-[10px] leading-tight text-[#8a8472] whitespace-nowrap">{tzName}</div>
        </div>
        <LangSwitcher />
        <div className="relative">
          <NotificationBell />
        </div>
        <button className="icon-btn" title={t("common.settings")} onClick={() => router.push("/settings")}><Settings /></button>
        <button className="hidden text-right text-sm sm:block" onClick={() => router.push("/profile")} title={t("common.profile")}>
          <div className="font-medium text-[#14110b]">{me?.name || "-"}</div>
          <div className="text-xs text-[#8a8472]">{me?.role || ""}</div>
        </button>
        <button className="btn px-2 sm:px-3" onClick={() => logout()} title={t("auth.logout")}>
          <LogOut className="h-4 w-4" />
          <span className="hidden sm:inline">{t("auth.logout")}</span>
        </button>
      </div>
    </header>
  );
}


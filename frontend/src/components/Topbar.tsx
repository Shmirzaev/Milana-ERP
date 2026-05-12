"use client";
import { useMe, logout } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import LangSwitcher from "@/components/LangSwitcher";
import NotificationBell from "@/components/NotificationBell";

export default function Topbar() {
  const { me } = useMe();
  const { t } = useT();
  return (
    <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between sticky top-0 z-10">
      <div className="text-sm text-slate-500">
        {me?.department ? `${t("top.department")}: ${me.department}` : null}
      </div>
      <div className="flex items-center gap-4">
        <LangSwitcher />
        <NotificationBell />
        <div className="text-sm">
          <div className="font-medium">{me?.name || "—"}</div>
          <div className="text-xs text-slate-500">{me?.role || ""}</div>
        </div>
        <button className="btn" onClick={() => logout()}>{t("auth.logout")}</button>
      </div>
    </header>
  );
}

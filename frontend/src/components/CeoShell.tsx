"use client";

import { LogOut } from "lucide-react";
import BrandLogo from "@/components/BrandLogo";
import LangSwitcher from "@/components/LangSwitcher";
import { logout } from "@/lib/auth";
import { useT } from "@/lib/i18n";

export default function CeoShell({ children }: { children: React.ReactNode }) {
  const { t } = useT();

  return (
    <div className="min-h-screen min-w-0">
      <header className="border-b border-[#e3dfd3] bg-[#fdfcf8]">
        <div className="mx-auto flex min-h-14 max-w-[1500px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-11">
          <BrandLogo alt="Milana" className="h-7 w-24 sm:w-28" />
          <div className="flex shrink-0 items-center gap-2">
            <LangSwitcher />
            <button type="button" className="btn" onClick={logout}>
              <LogOut className="h-4 w-4" aria-hidden="true" />
              {t("auth.logout")}
            </button>
          </div>
        </div>
      </header>
      <main className="min-w-0">{children}</main>
    </div>
  );
}

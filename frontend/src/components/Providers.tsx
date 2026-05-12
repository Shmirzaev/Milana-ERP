"use client";
import { LangProvider } from "@/lib/i18n";

export default function Providers({ children }: { children: React.ReactNode }) {
  return <LangProvider>{children}</LangProvider>;
}

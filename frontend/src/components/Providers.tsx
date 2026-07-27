"use client";
import { LangProvider } from "@/lib/i18n";
import { ThemeProvider } from "@/lib/theme";
import { DialogProvider } from "@/components/DialogProvider";

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <LangProvider>
        <DialogProvider>{children}</DialogProvider>
      </LangProvider>
    </ThemeProvider>
  );
}

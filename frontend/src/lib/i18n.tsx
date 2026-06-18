"use client";
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { dict } from "./i18n/dict";
import type { Lang } from "./i18n/types";

export type { Lang } from "./i18n/types";
export { LANG_NAMES } from "./i18n/types";

interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
  ready: boolean;
}

export type CtxT = Ctx["t"];

const LangCtx = createContext<Ctx | null>(null);

const STORAGE_KEY = "erp_lang";

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = localStorage.getItem(STORAGE_KEY) as Lang | null;
    if (saved && (saved === "en" || saved === "ru" || saved === "uz")) {
      setLangState(saved);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = (l: Lang) => {
    setLangState(l);
    if (typeof window !== "undefined") localStorage.setItem(STORAGE_KEY, l);
  };

  const value = useMemo<Ctx>(() => ({
    lang,
    setLang,
    ready,
    t(key, vars) {
      let v = dict[lang]?.[key] ?? dict.en[key] ?? key;
      if (vars) {
        for (const k of Object.keys(vars)) {
          v = v.replace(new RegExp(`\\{${k}\\}`, "g"), String(vars[k]));
        }
      }
      return v;
    },
  }), [lang, ready]);

  return <LangCtx.Provider value={value}>{children}</LangCtx.Provider>;
}

export function useT() {
  const ctx = useContext(LangCtx);
  if (!ctx) {
    // Provider not mounted yet (shouldn't happen in practice). Return a no-op.
    return {
      lang: "en" as Lang,
      setLang: () => {},
      ready: false,
      t: (k: string) => k,
    };
  }
  return ctx;
}

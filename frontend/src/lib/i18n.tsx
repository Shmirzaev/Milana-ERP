"use client";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import enBase from "./i18n/locales/en-base";
import enSupplemental from "./i18n/locales/en-supplemental";
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
type Messages = Record<string, string>;

const englishMessages: Messages = { ...enBase, ...enSupplemental };
const messageCache: Partial<Record<Lang, Messages>> = { en: englishMessages };
const messageLoaders: Record<Exclude<Lang, "en">, () => Promise<Messages>> = {
  ru: async () => {
    const [base, supplemental] = await Promise.all([
      import("./i18n/locales/ru-base"),
      import("./i18n/locales/ru-supplemental"),
    ]);
    return { ...base.default, ...supplemental.default };
  },
  uz: async () => {
    const [base, supplemental] = await Promise.all([
      import("./i18n/locales/uz-base"),
      import("./i18n/locales/uz-supplemental"),
    ]);
    return { ...base.default, ...supplemental.default };
  },
};

async function messagesFor(lang: Lang): Promise<Messages> {
  const cached = messageCache[lang];
  if (cached) return cached;
  const loaded = await messageLoaders[lang as Exclude<Lang, "en">]();
  messageCache[lang] = loaded;
  return loaded;
}

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  const [messages, setMessages] = useState<Messages>(englishMessages);
  const [ready, setReady] = useState(false);
  const languageRequestRef = useRef(0);

  const applyLanguage = useCallback(async (nextLang: Lang, persist: boolean) => {
    const requestId = ++languageRequestRef.current;
    setReady(false);
    const loaded = await messagesFor(nextLang);
    if (requestId !== languageRequestRef.current) return;
    setMessages(loaded);
    setLangState(nextLang);
    if (persist && typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, nextLang);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = localStorage.getItem(STORAGE_KEY) as Lang | null;
    if (saved && (saved === "en" || saved === "ru" || saved === "uz")) {
      void applyLanguage(saved, false);
    } else {
      setReady(true);
    }
  }, [applyLanguage]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((nextLang: Lang) => {
    void applyLanguage(nextLang, true);
  }, [applyLanguage]);

  const value = useMemo<Ctx>(() => ({
    lang,
    setLang,
    ready,
    t(key, vars) {
      let v = messages[key] ?? englishMessages[key] ?? key;
      if (vars) {
        for (const k of Object.keys(vars)) {
          v = v.replace(new RegExp(`\\{${k}\\}`, "g"), String(vars[k]));
        }
      }
      return v;
    },
  }), [lang, messages, ready, setLang]);

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

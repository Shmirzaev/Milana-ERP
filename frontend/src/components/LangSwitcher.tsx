"use client";
import { useEffect, useRef, useState } from "react";
import { Check, Globe2 } from "lucide-react";
import { LANG_NAMES, Lang, useT } from "@/lib/i18n";

const SHORT: Record<Lang, string> = { en: "EN", ru: "RU", uz: "UZ" };

export default function LangSwitcher() {
  const { lang, setLang, t } = useT();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const options: Lang[] = ["en", "ru", "uz"];

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className="icon-btn relative"
        title={t("top.language")}
        aria-label={`${t("top.language")}: ${LANG_NAMES[lang]}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Globe2 />
        <span className="absolute -bottom-0.5 -right-0.5 rounded bg-[#14110b] px-1 text-[8px] font-bold leading-3 text-[#fdfcf8]">
          {SHORT[lang]}
        </span>
      </button>

      {open && (
        <div
          className="absolute right-0 top-10 z-30 w-44 rounded-md border border-[#ded9ca] bg-[#fdfcf8] p-1 shadow-lg"
          role="menu"
          aria-label={t("top.language")}
        >
          {options.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => {
                setLang(l);
                setOpen(false);
              }}
              className={`flex w-full items-center justify-between rounded px-3 py-2 text-left text-sm transition ${
                lang === l
                  ? "bg-[#14110b] text-[#fdfcf8]"
                  : "text-[#56503f] hover:bg-[#f1efe8] hover:text-[#14110b]"
              }`}
              role="menuitemradio"
              aria-checked={lang === l}
            >
              <span>{LANG_NAMES[l]}</span>
              <span className="flex items-center gap-2 text-xs font-semibold">
                {SHORT[l]}
                {lang === l && <Check className="h-3.5 w-3.5" />}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

"use client";
import { LANG_NAMES, Lang, useT } from "@/lib/i18n";

const SHORT: Record<Lang, string> = { en: "EN", ru: "RU", uz: "UZ" };

export default function LangSwitcher() {
  const { lang, setLang, t } = useT();
  const options: Lang[] = ["en", "ru", "uz"];
  return (
    <div className="flex items-center gap-1" title={t("top.language")}>
      {options.map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLang(l)}
          className={`px-2 py-1 text-xs rounded border transition ${
            lang === l
              ? "bg-brand-500 text-white border-brand-500"
              : "bg-white text-slate-600 border-slate-300 hover:bg-slate-100"
          }`}
          aria-label={LANG_NAMES[l]}
        >
          {SHORT[l]}
        </button>
      ))}
    </div>
  );
}

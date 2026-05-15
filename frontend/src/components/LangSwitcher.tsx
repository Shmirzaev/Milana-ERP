"use client";
import { LANG_NAMES, Lang, useT } from "@/lib/i18n";

const SHORT: Record<Lang, string> = { en: "EN", ru: "RU", uz: "UZ" };

export default function LangSwitcher() {
  const { lang, setLang, t } = useT();
  const options: Lang[] = ["en", "ru", "uz"];
  return (
    <div
      className="inline-flex h-8 items-center rounded-md border border-[#ded9ca] bg-[#fdfcf8] p-0.5"
      title={t("top.language")}
    >
      {options.map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLang(l)}
          className={`h-6 min-w-[34px] rounded-[5px] px-2 text-[11px] font-medium transition ${
            lang === l
              ? "bg-[#14110b] text-[#fdfcf8]"
              : "bg-transparent text-[#8a8472] hover:bg-[#f1efe8] hover:text-[#14110b]"
          }`}
          aria-label={LANG_NAMES[l]}
          aria-pressed={lang === l}
        >
          {SHORT[l]}
        </button>
      ))}
    </div>
  );
}

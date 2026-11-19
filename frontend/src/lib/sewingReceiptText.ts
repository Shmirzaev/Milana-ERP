const text = {
  en: {
    keepOrUnassigned: "Keep current line / leave unassigned",
    legacyReceipt: "Legacy bundles without a Nastil are received without a new line assignment.",
  },
  ru: {
    keepOrUnassigned: "Сохранить линию / без назначения",
    legacyReceipt: "Старые связки без настила принимаются без нового назначения линии.",
  },
  uz: {
    keepOrUnassigned: "Joriy liniyani saqlash / biriktirmaslik",
    legacyReceipt: "Nastilsiz eski bog‘lamlar yangi liniyaga biriktirilmay qabul qilinadi.",
  },
} as const;

export function sewingReceiptText(lang: string) {
  return text[lang === "ru" || lang === "uz" ? lang : "en"];
}

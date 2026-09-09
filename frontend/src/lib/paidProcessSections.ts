import type { SectionCode } from "@/lib/modelPaidOperations";
import type { Lang } from "@/lib/i18n/types";

// Verified in the old ERP's stages.htm registry, 9 September 2026.
const LABELS: Record<Lang, Record<SectionCode, string>> = {
  en: { sewing: "Sewing", cutting: "Cutting", packaging: "Packaging", tikuv: "Tikuv", cleaning: "Cleaning", pressing: "Pressing", control: "Control", storage: "Storage", transfer: "Transfer", snaps: "Snaps", buttons: "Buttons", cord: "Cord", sorting: "Sorting" },
  ru: { sewing: "Пошив", cutting: "Крой", packaging: "Упаковка", tikuv: "Tikuv", cleaning: "Чистка", pressing: "Глажка", control: "Контроль", storage: "Склад", transfer: "Трансфер", snaps: "Кнопки", buttons: "Пуговицы", cord: "Шнур", sorting: "Тасниф" },
  uz: { sewing: "Tikish (Пошив)", cutting: "Bichish", packaging: "Qadoqlash", tikuv: "Tikuv", cleaning: "Tozalash", pressing: "Dazmollash", control: "Nazorat", storage: "Ombor", transfer: "Transfer", snaps: "Knopka", buttons: "Tugma", cord: "Shnur", sorting: "Tasnif" },
};
export function paidSectionLabel(section: SectionCode, lang: Lang): string { return LABELS[lang][section]; }

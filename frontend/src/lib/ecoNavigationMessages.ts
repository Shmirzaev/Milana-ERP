import { ecoAccessoriesText } from "./ecoAccessoriesText";
import type { Lang } from "./i18n/types";

export function ecoNavigationMessages(lang: Lang): Record<string, string> {
  const labels = {
    en: ["ECO COTTON inventory", "Fabric Inventory", "Accessories Inventory", "Accessory approval", "Incoming fabric transfers", "Send fabric to ECO COTTON"],
    ru: ["Склады ECO COTTON", "Склад тканей", "Склад фурнитуры", "Утверждение фурнитуры", "Входящие передачи ткани", "Отправка ткани в ECO COTTON"],
    uz: ["ECO COTTON omborlari", "Mato ombori", "Furnitura ombori", "Furniturani tasdiqlash", "Kiruvchi mato o‘tkazmalari", "ECO COTTONga mato yuborish"],
  }[lang];
  return Object.fromEntries([
    ...["section", "fabric", "accessory", "approval", "incoming", "dispatch"].map((key, index) => [`ecoMaterials.${key}`, labels[index]]),
    ...Object.entries(ecoAccessoriesText[lang].errors).map(([key, value]) => [`ecoAccessories.${key}`, value]),
  ]);
}

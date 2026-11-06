import type { Lang } from "./i18n/types";

export type ShipmentScanResult = {
  sign: string;
  message?: string;
  package_no?: string | null;
  package_quantity?: number | null;
  previous_scan?: {
    shipment_no: string;
    customer_name?: string | null;
    scanned_by_name?: string | null;
    scanned_at: string;
  } | null;
};

const copy = {
  en: { already: "Package already scanned", shipment: "Shipment", customer: "Customer", by: "Scanned by", when: "Scanned at", unknown: "Not recorded" },
  ru: { already: "Упаковка уже отсканирована", shipment: "Отгрузка", customer: "Клиент", by: "Кто сканировал", when: "Дата сканирования", unknown: "Не указано" },
  uz: { already: "Qadoq avval skanerlangan", shipment: "Jo‘natma", customer: "Mijoz", by: "Skanerlagan", when: "Skanerlangan vaqt", unknown: "Qayd etilmagan" },
};

export function successfulShipmentScanMessage(result: ShipmentScanResult, lang: Lang): string | null {
  const quantity = result.package_quantity;
  if (result.sign !== "success" || quantity == null || !Number.isInteger(quantity) || quantity < 0) return null;
  const message = {
    en: `${quantity} ${quantity === 1 ? "piece" : "pieces"} scanned.`,
    ru: `Отсканировано: ${quantity} шт.`,
    uz: `${quantity} dona skanerlandi.`,
  }[lang];
  return result.package_no ? `${result.package_no} · ${message}` : message;
}

export function previousShipmentScanMessage(result: ShipmentScanResult, lang: Lang): string | null {
  const scan = result.previous_scan;
  if (!scan) return null;
  const text = copy[lang];
  const date = new Date(scan.scanned_at);
  const when = Number.isNaN(date.getTime()) ? text.unknown : date.toLocaleString(
    { en: "en-GB", ru: "ru-RU", uz: "uz-UZ" }[lang],
    { timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false },
  );
  return `${text.already}${result.package_no ? `: ${result.package_no}` : ""}. ${text.customer}: ${scan.customer_name || text.unknown}. ${text.shipment}: ${scan.shipment_no}. ${text.by}: ${scan.scanned_by_name || text.unknown}. ${text.when}: ${when} (UTC+05:00).`;
}

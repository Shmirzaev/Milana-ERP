import type { EcoMaterialItem, EcoMaterialKind } from "./ecoInventory";
import type { EcoReceiptBody } from "./ecoReceipt";
import { InventoryQcStatus } from "./inventoryQcStatus";

export type EcoReceiptRow = {
  key: string; category: EcoMaterialItem["category"]; item_id: number | null; batch_no: string;
  unit: string; quantity: string; mode: "total" | "rolls" | "length"; weights: string[]; lengths: string[];
  cost_per_unit: string; qc_status: InventoryQcStatus; details: Record<string, string>;
};
export function newEcoReceiptRow(kind: EcoMaterialKind): EcoReceiptRow {
  return {key: crypto.randomUUID(), category: kind, item_id: null, batch_no: "", unit: kind === "fabric" ? "kg" : "pcs",
    quantity: "", mode: "total", weights: [""], lengths: [""], cost_per_unit: "0", qc_status: InventoryQcStatus.PASSED, details: {}};
}
export function ecoReceiptRowBody(row: EcoReceiptRow, kind: EcoMaterialKind): Omit<EcoReceiptBody, "request_key"> {
  const individual = kind === "fabric" && row.mode === "rolls";
  // Sum integer ten-thousandths, matching the stock quantity scale without binary-float drift.
  const quantity = individual ? (row.weights.reduce((sum, raw) => {
    const [whole = "0", fraction = ""] = raw.split(".");
    return sum + BigInt(whole || "0") * 10000n + BigInt(fraction.padEnd(4, "0").slice(0, 4));
  }, 0n)) : null;
  const total = quantity === null ? row.quantity : `${quantity / 10000n}.${String(quantity % 10000n).padStart(4, "0")}`;
  const d = row.details;
  return {kind, item_id: row.item_id!, batch_no: row.batch_no.trim(), unit: row.unit, quantity: total,
    color: d.color?.trim() || null, cost_per_unit: row.cost_per_unit, qc_status: row.qc_status,
    notes: d.notes || null, old_code: d.old_code || null, color_code: d.color_code || null,
    color_status: d.color_status || null, width: d.width || null, gsm: d.gsm || null,
    length_m: row.mode === "length" ? total : d.length_m || null,
    piece_count: individual ? row.weights.length : d.piece_count ? Number(d.piece_count) : null,
    roll_weights_kg: individual ? row.weights : [], roll_lengths_m: individual ? row.lengths.map(value => value || null) : [],
    processes: d.processes || null, image_url: d.image_url || null};
}
export const ecoReceiptTableText = (lang: string) => ({
  // Values below follow the existing application language selection.
  en: {noSupplier: "No supplier", imageAdded: "Image added", addRow: "Add row", remove: "Remove row", details: "More details", type: "Type", name: "Name", fabric: "Fabric", semi_finished: "Semi-finished fabric", accessory: "Accessory", packaging: "Packaging", keyboard: "Press Enter in a batch number to add another row. Save receives all rows together.", rowError: "Complete every row: name, batch number and a positive quantity. Check roll weights and counts.", maxRows: "Up to 100 rows per receipt."},
  ru: {noSupplier: "Без поставщика", imageAdded: "Фото добавлено", addRow: "Добавить строку", remove: "Удалить строку", details: "Дополнительные данные", type: "Тип", name: "Название", fabric: "Ткань", semi_finished: "Полуфабрикат", accessory: "Фурнитура", packaging: "Упаковка", keyboard: "Enter в номере партии добавляет строку. Сохранение принимает все строки вместе.", rowError: "Заполните каждую строку: название, партия и положительное количество. Проверьте вес и число рулонов.", maxRows: "До 100 строк на одно поступление."},
  uz: {noSupplier: "Yetkazib beruvchisiz", imageAdded: "Rasm yuklandi", addRow: "Qator qo‘shish", remove: "Qatorni o‘chirish", details: "Qo‘shimcha ma’lumot", type: "Tur", name: "Nomi", fabric: "Mato", semi_finished: "Yarim tayyor mato", accessory: "Furnitura", packaging: "Qadoqlash", keyboard: "Partiya raqamida Enter bosib qator qo‘shing. Saqlash barcha qatorlarni birga qabul qiladi.", rowError: "Har bir qatorda nom, partiya va musbat miqdorni kiriting. Rulon vazni va sonini tekshiring.", maxRows: "Bitta kirimda 100 tagacha qator."},
}[lang === "ru" ? "ru" : lang === "uz" ? "uz" : "en"]);

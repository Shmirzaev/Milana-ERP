import type { EcoMaterialKind } from "./ecoInventory";
import { InventoryQcStatus } from "./inventoryQcStatus";

export type EcoReceiptSource = "opening_balance" | "purchase" | "other";
export type EcoReceiptDetails = {
  source?: EcoReceiptSource; supplier_id?: number | null; supplier_name?: string | null;
  warehouse_id?: number | null; warehouse_name?: string | null; production_order_id?: number | null;
  document_no?: string | null; received_date?: string | null; unit?: string | null; cost_per_unit?: string;
  qc_status?: InventoryQcStatus; old_code?: string | null; color_code?: string | null; color_status?: string | null;
  width?: string | null; gsm?: string | null; length_m?: string | null; piece_count?: number | null;
  roll_weights_kg?: string[]; roll_lengths_m?: (string | null)[]; processes?: string | null; image_url?: string | null;
};
export type EcoReceiptBody = EcoReceiptDetails & {
  request_key: string; kind: EcoMaterialKind; item_id: number; batch_no: string; color: string | null; quantity: string; notes: string | null;
};
export type EcoReceiptBulkBody = { request_key: string; lines: Omit<EcoReceiptBody, "request_key">[] };
const text = {
  en: { catalog: "Materials and suppliers", addFabric: "Add / edit fabric types", addAccessory: "Add / edit accessory types", source: "Receipt type", opening_balance: "Opening stock", purchase: "Supplier delivery", other: "Other receipt", document: "Delivery document / reference", receivedDate: "Receipt date", addWarehouse: "Add ECO warehouse", warehouseName: "Warehouse name", details: "Receipt details", shared: "Material types and suppliers use the shared Milana catalog. ECO stock balances remain separate.", hold: "On hold", rejected: "Rejected", width: "Fabric width", length: "Total length (m)", cost: "Unit cost", total: "Stock value", inspection: "Quality status", invalid: "Check the quantity, warehouse and roll totals.", receiptHelp: "Enter existing stock as Opening stock. For new deliveries, select Supplier delivery. Confirm fabric sent by Milana in Incoming transfers." },
  ru: { catalog: "Материалы и поставщики", addFabric: "Добавить / изменить виды ткани", addAccessory: "Добавить / изменить виды фурнитуры", source: "Вид поступления", opening_balance: "Начальные остатки", purchase: "Поставка от поставщика", other: "Прочее поступление", document: "Накладная / документ", receivedDate: "Дата приёма", addWarehouse: "Добавить склад ECO", warehouseName: "Название склада", details: "Данные поступления", shared: "Виды материалов и поставщики общие с Milana. Остатки ECO учитываются отдельно.", hold: "На удержании", rejected: "Отклонено", width: "Ширина ткани", length: "Общая длина (м)", cost: "Цена за единицу", total: "Стоимость остатка", inspection: "Контроль качества", invalid: "Проверьте количество, склад и итог веса рулонов.", receiptHelp: "Для имеющегося запаса выберите начальные остатки. Для новых поставок — поставку от поставщика. Ткань из Milana подтверждайте во входящих передачах." },
  uz: { catalog: "Materiallar va yetkazib beruvchilar", addFabric: "Mato turlarini qo‘shish / tahrirlash", addAccessory: "Furnitura turlarini qo‘shish / tahrirlash", source: "Kirim turi", opening_balance: "Boshlang‘ich qoldiq", purchase: "Yetkazib beruvchidan kirim", other: "Boshqa kirim", document: "Yuk xati / hujjat raqami", receivedDate: "Qabul sanasi", addWarehouse: "ECO omborini qo‘shish", warehouseName: "Ombor nomi", details: "Kirim tafsilotlari", shared: "Material turlari va yetkazib beruvchilar Milana bilan umumiy katalogda. ECO qoldiqlari alohida hisoblanadi.", hold: "To‘xtatilgan", rejected: "Rad etilgan", width: "Mato eni", length: "Jami uzunlik (m)", cost: "Birlik narxi", total: "Qoldiq qiymati", inspection: "Sifat holati", invalid: "Miqdor, ombor va rulonlar jami vaznini tekshiring.", receiptHelp: "Mavjud zaxira uchun boshlang‘ich qoldiqni tanlang. Yangi yetkazmalar uchun yetkazib beruvchidan kirimni tanlang. Milanadan kelgan matoni kiruvchi o‘tkazmalarda tasdiqlang." },
};
export function ecoReceiptText(lang: string) { return text[lang === "ru" ? "ru" : lang === "uz" ? "uz" : "en"]; }

export function ecoQualityText(value: string, t: (key: string) => string, labels: ReturnType<typeof ecoReceiptText>) { return value === "hold" ? labels.hold : value === "rejected" ? labels.rejected : t(`qc.${value}`); }

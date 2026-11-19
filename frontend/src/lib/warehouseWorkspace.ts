import { modelSearchIncludes } from "@/lib/modelCode";

export type WarehouseSearchRow = {
  model_id?: number | null; model_code?: string | null; model_name?: string | null;
  order_no?: string | null; sales_order_no?: string | null; production_no?: string | null;
  package_no?: string | null; barcode?: string | null; color?: string | null;
  storage_cell?: string | null; storage_shelf?: string | null; status?: string | null;
};

export function warehouseVariantKey(row: WarehouseSearchRow) {
  return String(row.model_id || row.model_code || row.model_name || row.package_no || "");
}

export function warehouseMatches<T extends WarehouseSearchRow>(rows: T[], query: string, variant: string): T[] {
  const selected = variant ? rows.filter(row => warehouseVariantKey(row) === variant) : rows;
  const q = query.trim().toLocaleLowerCase();
  if (!q) return selected;
  const modelMatches = selected.filter(row => modelSearchIncludes(row.model_code, q));
  if (modelMatches.length) return modelMatches;
  return selected.filter(row => [row.order_no, row.sales_order_no, row.production_no, row.model_name,
    row.package_no, row.barcode, row.color, row.storage_cell, row.storage_shelf, row.status]
    .some(value => String(value || "").toLocaleLowerCase().includes(q)));
}

export const warehouseWorkspaceText = {
  en: { variant: "Model / variant", all: "All models and variants", clear: "Clear selection", matches: "Matching packages", location: "Placement and move", unplaced: "Unplaced", report: "Shipment report" },
  ru: { variant: "Модель / вариант", all: "Все модели и варианты", clear: "Сбросить выбор", matches: "Найденные упаковки", location: "Размещение и перемещение", unplaced: "Без ячейки", report: "Отчёт по отгрузкам" },
  uz: { variant: "Model / variant", all: "Barcha model va variantlar", clear: "Tanlovni tozalash", matches: "Topilgan paketlar", location: "Joylashtirish va ko‘chirish", unplaced: "Joylashtirilmagan", report: "Jo‘natmalar hisoboti" },
};

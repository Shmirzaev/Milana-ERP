export const shipmentDisplayText = {
  en: { excel: "Invoice Excel", back: "Back to shipments", open: "Open shipment", expand: "Expand shipment", collapse: "Collapse shipment", expandAll: "Expand all", collapseAll: "Collapse all" },
  ru: { excel: "Накладная Excel", back: "Назад к отгрузкам", open: "Открыть отгрузку", expand: "Развернуть отгрузку", collapse: "Свернуть отгрузку", expandAll: "Развернуть все", collapseAll: "Свернуть все" },
  uz: { excel: "Hisob-faktura Excel", back: "Jo‘natmalarga qaytish", open: "Jo‘natmani ochish", expand: "Jo‘natmani ochish", collapse: "Jo‘natmani yig‘ish", expandAll: "Barchasini ochish", collapseAll: "Barchasini yig‘ish" },
};

export function shipmentStatusClass(status: string): string {
  if (["shipped", "delivered"].includes(status)) return "border-emerald-300 bg-emerald-50 text-emerald-800";
  if (["draft", "created"].includes(status)) return "border-red-300 bg-red-50 text-red-800";
  return "border-stone-300 bg-stone-50 text-stone-600";
}

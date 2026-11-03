export type EcoMaterialKind = "fabric" | "accessory";
export type EcoMovementKind = "receive" | "transfer_receipt" | "consume" | "issue";
export type FabricTransferStatus = "in_transit" | "partially_received" | "received";
export type EcoBatch = { id: number; item_id: number; item_name: string; sku: string; kind: EcoMaterialKind;
  batch_no: string; color: string | null; unit: string; quantity: string; reserved_quantity: string;
  available_quantity: string; received_at: string };
export type EcoMaterialItem = { id: number; name: string; sku: string; unit: string; kind: EcoMaterialKind };
export type EcoMovement = { id: number; batch_id: number; batch_no: string; item_name: string; unit: string;
  kind: EcoMovementKind; quantity: string; order_no: string | null; notes: string | null; created_at: string; operator_name: string };
export type FabricSourceBatch = { id: number; item_name: string; batch_no: string; color: string | null;
  unit: string; quantity: string; available_quantity: string };
export type FabricTransferLine = { id: number; source_batch_id: number; item_id: number; item_name: string;
  batch_no: string; color: string | null; unit: string; quantity: string; received_quantity: string };
export type FabricTransfer = { id: number; number: string; status: FabricTransferStatus; dispatched_at: string;
  operator_name: string; notes: string | null; lines: FabricTransferLine[] };

const labels = {
  en: {
    title: "ECO COTTON inventory", fabric: "Fabric inventory", accessory: "Accessories inventory", stock: "Stock", history: "Inventory history",
    receive: "Receive materials", consume: "Record consumption", item: "Material", batch: "Batch", color: "Color", quantity: "Quantity", unit: "Unit",
    available: "Available", reserved: "Allocated", balance: "On hand", date: "Date", operator: "Operator", notes: "Notes", save: "Save", cancel: "Cancel",
    loading: "Loading…", empty: "No records found", denied: "Access is unavailable in this factory or for this account.", error: "The operation failed.",
    saved: "Saved. Stock and history have been updated.", select: "Select a material", search: "Search material, batch or color", actions: "Actions",
    accessoryHelp: "Approve and issue accessories through the production accessory plan before sewing.", plans: "Accessory approvals",
    receiveHint: "Record materials physically received at ECO COTTON. Milana deliveries must be confirmed in Incoming transfers.",
    consumeHint: "Consumption reduces available fabric stock. Allocated stock cannot be consumed here.",
    transfers: "Milana → ECO COTTON fabric", transferHint: "Track fabric from Milana dispatch to ECO COTTON receipt.", dispatch: "Dispatch fabric", incoming: "Incoming transfers",
    add: "Add fabric", remove: "Remove", sent: "Sent", received: "Received", outstanding: "Outstanding", status: "Status", all: "All statuses",
    in_transit: "In transit", partially_received: "Partially received", receivedStatus: "Received", excel: "Excel delivery document", confirmReceive: "Confirm receipt",
    receiptHint: "Enter quantities physically received now. Leave missing quantities at zero; they remain outstanding.", dispatchHint: "Dispatch deducts Milana available stock. ECO COTTON receives stock only after confirming receipt.",
    retry: "Retry the same operation", retryHint: "The result is uncertain. Retry with the same quantities to avoid a duplicate movement.",
    filter: "Filter", previous: "Previous", next: "Next", draft: "Dispatch contents", validQuantity: "Enter a positive quantity within the available balance.",
    receiveNow: "Receive now", productionOrder: "Production order (optional)", none: "No production order", confirm: "Confirm", confirmDispatch: "Dispatch these fabrics to ECO COTTON?",
  },
  ru: {
    title: "Склад ECO COTTON", fabric: "Склад тканей", accessory: "Склад фурнитуры", stock: "Остатки", history: "История склада",
    receive: "Принять материалы", consume: "Записать расход", item: "Материал", batch: "Партия", color: "Цвет", quantity: "Количество", unit: "Ед.",
    available: "Доступно", reserved: "Выделено", balance: "На складе", date: "Дата", operator: "Сотрудник", notes: "Примечание", save: "Сохранить", cancel: "Отмена",
    loading: "Загрузка…", empty: "Записи не найдены", denied: "Доступ недоступен для этой фабрики или учётной записи.", error: "Не удалось выполнить операцию.",
    saved: "Сохранено. Остатки и история обновлены.", select: "Выберите материал", search: "Поиск по материалу, партии или цвету", actions: "Действия",
    accessoryHelp: "Согласуйте и выдайте фурнитуру через заявку производства до передачи в пошив.", plans: "Согласование фурнитуры",
    receiveHint: "Укажите материалы, фактически принятые на ECO COTTON. Поставки из Milana подтверждайте во входящих передачах.",
    consumeHint: "Расход уменьшает доступный остаток ткани. Выделенный запас здесь расходовать нельзя.",
    transfers: "Передача ткани Milana → ECO COTTON", transferHint: "Отслеживайте ткань от отправки Milana до приёмки ECO COTTON.", dispatch: "Отправить ткань", incoming: "Входящие передачи",
    add: "Добавить ткань", remove: "Удалить", sent: "Отправлено", received: "Принято", outstanding: "В пути", status: "Статус", all: "Все статусы",
    in_transit: "В пути", partially_received: "Частично принято", receivedStatus: "Принято", excel: "Накладная Excel", confirmReceive: "Подтвердить приёмку",
    receiptHint: "Введите фактически принятые сейчас количества. Для недостающих оставьте ноль — они останутся в пути.", dispatchHint: "Отправка уменьшает доступный остаток Milana. Остаток ECO COTTON пополняется после подтверждения приёмки.",
    retry: "Повторить операцию", retryHint: "Результат неизвестен. Повторите с теми же количествами, чтобы избежать повторного движения.",
    filter: "Фильтр", previous: "Назад", next: "Далее", draft: "Состав передачи", validQuantity: "Введите положительное количество в пределах доступного остатка.",
    receiveNow: "Принять сейчас", productionOrder: "Заказ производства (необязательно)", none: "Без заказа производства", confirm: "Подтвердить", confirmDispatch: "Отправить эти ткани в ECO COTTON?",
  },
  uz: {
    title: "ECO COTTON ombori", fabric: "Mato ombori", accessory: "Furnitura ombori", stock: "Qoldiqlar", history: "Ombor tarixi",
    receive: "Materiallarni qabul qilish", consume: "Sarfni qayd etish", item: "Material", batch: "Partiya", color: "Rang", quantity: "Miqdor", unit: "Birlik",
    available: "Mavjud", reserved: "Ajratilgan", balance: "Omborda", date: "Sana", operator: "Xodim", notes: "Izoh", save: "Saqlash", cancel: "Bekor qilish",
    loading: "Yuklanmoqda…", empty: "Yozuvlar topilmadi", denied: "Ushbu fabrika yoki hisob uchun ruxsat yo‘q.", error: "Amal bajarilmadi.",
    saved: "Saqlandi. Qoldiqlar va tarix yangilandi.", select: "Material tanlang", search: "Material, partiya yoki rang bo‘yicha qidirish", actions: "Amallar",
    accessoryHelp: "Tikishga yuborishdan oldin furniturani ishlab chiqarish rejasi orqali tasdiqlang va bering.", plans: "Furniturani tasdiqlash",
    receiveHint: "ECO COTTONda amalda qabul qilingan materiallarni kiriting. Milana yetkazmalarini kiruvchi o‘tkazmalarda tasdiqlang.",
    consumeHint: "Sarf mavjud mato qoldig‘ini kamaytiradi. Ajratilgan zaxirani bu yerda sarflab bo‘lmaydi.",
    transfers: "Milana → ECO COTTON mato o‘tkazmalari", transferHint: "Matoni Milana jo‘natishidan ECO COTTON qabuligacha kuzating.", dispatch: "Mato jo‘natish", incoming: "Kiruvchi o‘tkazmalar",
    add: "Mato qo‘shish", remove: "O‘chirish", sent: "Yuborildi", received: "Qabul qilindi", outstanding: "Yo‘lda", status: "Holat", all: "Barcha holatlar",
    in_transit: "Yo‘lda", partially_received: "Qisman qabul qilindi", receivedStatus: "Qabul qilindi", excel: "Excel yuk xati", confirmReceive: "Qabulni tasdiqlash",
    receiptHint: "Hozir amalda qabul qilingan miqdorlarni kiriting. Yetishmagan miqdorlar uchun nol qoldiring — ular yo‘lda qoladi.", dispatchHint: "Jo‘natish Milana mavjud qoldig‘ini kamaytiradi. ECO COTTON qoldig‘i qabul tasdiqlangandan keyin oshadi.",
    retry: "Amalni takrorlash", retryHint: "Natija noma’lum. Takroriy harakatdan saqlanish uchun aynan shu miqdorlar bilan qayta urining.",
    filter: "Filtr", previous: "Oldingi", next: "Keyingi", draft: "O‘tkazma tarkibi", validQuantity: "Mavjud qoldiqdan oshmagan musbat miqdor kiriting.",
    receiveNow: "Hozir qabul qilish", productionOrder: "Ishlab chiqarish buyurtmasi (ixtiyoriy)", none: "Buyurtmasiz", confirm: "Tasdiqlash", confirmDispatch: "Ushbu matolar ECO COTTONga jo‘natilsinmi?",
  },
};
export function ecoInventoryText(language: string) { return labels[language === "ru" ? "ru" : language === "uz" ? "uz" : "en"]; }
export function transferStatusText(status: FabricTransferStatus, text: ReturnType<typeof ecoInventoryText>) {
  return status === "received" ? text.receivedStatus : text[status];
}
export function fabricTransferOutstanding(line: Pick<FabricTransferLine, "quantity" | "received_quantity">): number {
  return (Math.round(Number(line.quantity) * 10000) - Math.round(Number(line.received_quantity) * 10000)) / 10000;
}

export function saveEcoPendingAttempt(key: string | null, attempt: unknown | null) {
  if (!key) return;
  try { if (attempt === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, JSON.stringify(attempt)); } catch { /* The in-memory attempt still retains the same key if browser storage is unavailable. */ }
}
export function loadEcoPendingAttempt<T>(key: string): T | null {
  try { const saved = sessionStorage.getItem(key); return saved ? JSON.parse(saved) as T : null; } catch { return null; }
}

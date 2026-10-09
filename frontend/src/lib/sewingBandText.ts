import type { Lang } from "./i18n/types";

const en = {
  floor: "Sewing Floor", flows: "Sewing Flows", report: "Daily Sewing Report", receive: "Receive bundles",
  available: "Available — needs work", reported: "Reported progress", actual: "Actual output recorded", remaining: "Remaining",
  finalPending: "Awaiting final order output", history: "Completed line work", order: "Order", model: "Model", batch: "Batch",
  scan: "Scan bundle QR / barcode", receiveButton: "Receive and assign to my band", search: "Find a batch to receive", searchButton: "Search",
  choose: "Select assigned work", sewn: "Sewn today", date: "Work date", save: "Save report", saved: "Saved", received: "Received and assigned",
  repeated: "Already received by this band", twoPart: "Two-part garment", top: "Top", bottom: "Bottom", defects: "Defective quantity",
  reason: "Reason", notes: "Notes", edit: "Edit", cancel: "Cancel", noReports: "No reports for this date", loading: "Loading…", retry: "Retry",
  final: "Enter final output", finalSave: "Save actual order output", passed: "Accepted pieces", failed: "Defective pieces",
  finalHint: "This records actual order output and hands accepted pieces to the next production stage. Daily reports remain separate.",
  reportHint: "Enter today's quantity only. For two-part garments, progress counts complete top/bottom pairs.",
  finish: "Finish line work", reopen: "Reopen line work", finishReason: "Reason for finishing or reopening this line assignment",
  finishHint: "This frees the band without recording actual order output.", logout: "Sign out", emptyReceive: "No eligible batches found",
  discrepancy: "Reported / actual", close: "Close", language: "Language", filter: "Filter bands or orders",
};
const ru: typeof en = {
  floor: "Швейный цех", flows: "Швейные линии", report: "Ежедневный швейный отчёт", receive: "Приём пачек",
  available: "Свободна — нужно назначить работу", reported: "Прогресс по отчётам", actual: "Фактический выпуск", remaining: "Осталось",
  finalPending: "Ожидается итоговый выпуск по заказу", history: "Завершённая работа линии", order: "Заказ", model: "Модель", batch: "Партия",
  scan: "Сканировать QR / штрихкод пачки", receiveButton: "Принять и назначить моей бригаде", search: "Найти партию для приёма", searchButton: "Поиск",
  choose: "Выберите назначенную работу", sewn: "Сшито сегодня", date: "Дата работы", save: "Сохранить отчёт", saved: "Сохранено", received: "Принято и назначено",
  repeated: "Уже принято этой бригадой", twoPart: "Изделие из двух частей", top: "Верх", bottom: "Низ", defects: "Количество брака",
  reason: "Причина", notes: "Примечание", edit: "Изменить", cancel: "Отмена", noReports: "Нет отчётов за эту дату", loading: "Загрузка…", retry: "Повторить",
  final: "Ввести итоговый выпуск", finalSave: "Сохранить фактический выпуск", passed: "Годные изделия", failed: "Бракованные изделия",
  finalHint: "Записывает фактический выпуск и передаёт годные изделия на следующий этап. Ежедневные отчёты учитываются отдельно.",
  reportHint: "Введите количество только за сегодня. Для двухчастных изделий прогресс считается по полным парам верха и низа.",
  finish: "Завершить работу линии", reopen: "Возобновить работу линии", finishReason: "Причина завершения или возобновления работы линии",
  finishHint: "Освобождает бригаду без записи фактического выпуска.", logout: "Выйти", emptyReceive: "Нет доступных партий",
  discrepancy: "По отчётам / фактически", close: "Закрыть", language: "Язык", filter: "Поиск бригады или заказа",
};
const uz: typeof en = {
  floor: "Tikuv sexi", flows: "Tikuv liniyalari", report: "Kunlik tikuv hisoboti", receive: "Bog‘lamlarni qabul qilish",
  available: "Bo‘sh — ish biriktirish kerak", reported: "Hisobot bo‘yicha bajarilish", actual: "Qayd etilgan haqiqiy chiqim", remaining: "Qoldiq",
  finalPending: "Buyurtmaning yakuniy chiqimi kutilmoqda", history: "Liniyaning tugallangan ishlari", order: "Buyurtma", model: "Model", batch: "Partiya",
  scan: "Bog‘lam QR / shtrixkodini skanerlang", receiveButton: "Qabul qilib, mening bandimga biriktirish", search: "Qabul qilish uchun partiyani topish", searchButton: "Qidirish",
  choose: "Biriktirilgan ishni tanlang", sewn: "Bugun tikilgan", date: "Ish sanasi", save: "Hisobotni saqlash", saved: "Saqlandi", received: "Qabul qilindi va biriktirildi",
  repeated: "Bu band tomonidan avval qabul qilingan", twoPart: "Ikki qismli kiyim", top: "Ustki qism", bottom: "Pastki qism", defects: "Nuqsonli soni",
  reason: "Sabab", notes: "Izoh", edit: "Tahrirlash", cancel: "Bekor qilish", noReports: "Bu sana uchun hisobot yo‘q", loading: "Yuklanmoqda…", retry: "Qayta urinish",
  final: "Yakuniy chiqimni kiritish", finalSave: "Haqiqiy chiqimni saqlash", passed: "Yaroqli dona", failed: "Nuqsonli dona",
  finalHint: "Haqiqiy chiqimni qayd etib, yaroqli donalarni keyingi bosqichga uzatadi. Kunlik hisobotlar alohida hisoblanadi.",
  reportHint: "Faqat bugungi sonni kiriting. Ikki qismli kiyimlarda bajarilish to‘liq ustki/pastki juftliklar bo‘yicha hisoblanadi.",
  finish: "Liniya ishini tugatish", reopen: "Liniya ishini qayta ochish", finishReason: "Liniya ishini tugatish yoki qayta ochish sababi",
  finishHint: "Haqiqiy chiqimni qayd etmasdan bandni bo‘shatadi.", logout: "Chiqish", emptyReceive: "Mos partiyalar topilmadi",
  discrepancy: "Hisobot / haqiqat", close: "Yopish", language: "Til", filter: "Band yoki buyurtmani qidirish",
};
export const sewingBandText = (lang: Lang) => ({ en, ru, uz })[lang];

export type BandJob = {
  id: number; work_order_id: number; production_order_id: number; production_batch_id: number | null;
  order_no: string; model: string | null; batch: string | null; quantity: number; reported_qty: number;
  actual_qty: number; actual_defective_qty?: number; top_qty: number; bottom_qty: number; line_finished: boolean; awaiting_final: boolean;
  finish_reason: string | null; status: string;
};
export type Band = { id: number; name: string; code: string; jobs: BandJob[] };

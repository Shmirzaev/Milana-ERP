export const messages = {
  en: {
    title: "Production overview", subtitle: "All factories · Production orders and recorded output",
    active: "Active production orders", current: "Current workload · all dates", planned: "Planned pieces", late: "Overdue orders", packed: "Packed pieces",
    period: "Selected period", trend: "Daily production output", records: "Recorded pieces by stage · Tashkent time", stages: "Orders by stage", breakdown: "Current active orders", department: "Output by department", note: "Stage totals are separate operations; do not add them as finished garments.",
    orders: "Active production", all: "All types", client: "Client orders", branded: "Branded stock", service: "Service orders", number: "Production order", type: "Type", quantity: "Plan, pcs", status: "Stage", deadline: "Deadline", view: "View all orders", none: "No active orders match this filter.", empty: "No output recorded in this period.", error: "Dashboard data could not be loaded. Please retry.", stale: "Refresh failed. Previously loaded data is shown.", refresh: "Refresh", export: "Export daily output", days7: "Last 7 days", days30: "Last 30 days", days90: "Last 90 days", loading: "Loading dashboard…", updated: "Updated", details: "Chart data", limited: "Showing the first 100 orders by deadline.", noDeadline: "Not set", newOrder: "New order", finance: "Finance · all time", revenue: "Revenue invoiced", payments: "Payments received", financeError: "Finance data unavailable", total: "orders", search: "Find an order", noStages: "No active production orders", from: "From", to: "To",
  },
  ru: {
    title: "Обзор производства", subtitle: "Все фабрики · Производственные заказы и учтённый выпуск",
    active: "Активные производственные заказы", current: "Текущая загрузка · все даты", planned: "План, шт.", late: "Просроченные заказы", packed: "Упаковано, шт.",
    period: "Выбранный период", trend: "Ежедневный выпуск", records: "Учтённые изделия по этапам · время Ташкента", stages: "Заказы по этапам", breakdown: "Текущие активные заказы", department: "Выпуск по отделам", note: "Итоги этапов — отдельные операции; их сумма не равна числу готовых изделий.",
    orders: "Активное производство", all: "Все типы", client: "Клиентские заказы", branded: "Брендовый склад", service: "Услуги", number: "Производственный заказ", type: "Тип", quantity: "План, шт.", status: "Этап", deadline: "Срок", view: "Все заказы", none: "Нет активных заказов по выбранному фильтру.", empty: "За этот период выпуск не зарегистрирован.", error: "Не удалось загрузить данные. Повторите попытку.", stale: "Ошибка обновления. Показаны ранее загруженные данные.", refresh: "Обновить", export: "Экспорт выпуска по дням", days7: "Последние 7 дней", days30: "Последние 30 дней", days90: "Последние 90 дней", loading: "Загрузка…", updated: "Обновлено", details: "Данные графика", limited: "Первые 100 заказов по сроку.", noDeadline: "Не задан", newOrder: "Новый заказ", finance: "Финансы · всё время", revenue: "Выставлено счетов", payments: "Получено оплат", financeError: "Финансовые данные недоступны", total: "заказов", search: "Найти заказ", noStages: "Нет активных производственных заказов", from: "С", to: "По",
  },
  uz: {
    title: "Ishlab chiqarish sharhi", subtitle: "Barcha fabrikalar · Ishlab chiqarish buyurtmalari va qayd etilgan natijalar",
    active: "Faol ishlab chiqarish buyurtmalari", current: "Joriy ishlar · barcha sanalar", planned: "Reja, dona", late: "Muddati o'tgan buyurtmalar", packed: "Qadoqlangan, dona",
    period: "Tanlangan davr", trend: "Kunlik ishlab chiqarish", records: "Bosqichlar bo'yicha qayd etilgan dona · Toshkent vaqti", stages: "Bosqichlar bo'yicha buyurtmalar", breakdown: "Joriy faol buyurtmalar", department: "Bo'limlar bo'yicha ishlab chiqarish", note: "Bosqich natijalari alohida amallardir; ularning yig'indisi tayyor kiyimlar soni emas.",
    orders: "Faol ishlab chiqarish", all: "Barcha turlar", client: "Mijoz buyurtmalari", branded: "Brend ombori", service: "Xizmat buyurtmalari", number: "Ishlab chiqarish buyurtmasi", type: "Tur", quantity: "Reja, dona", status: "Bosqich", deadline: "Muddat", view: "Barcha buyurtmalar", none: "Ushbu filtr bo'yicha faol buyurtma yo'q.", empty: "Bu davrda ishlab chiqarish qayd etilmagan.", error: "Ma'lumotlar yuklanmadi. Qayta urining.", stale: "Yangilash bajarilmadi. Avvalgi ma'lumotlar ko'rsatilmoqda.", refresh: "Yangilash", export: "Kunlik natijalarni eksport qilish", days7: "Oxirgi 7 kun", days30: "Oxirgi 30 kun", days90: "Oxirgi 90 kun", loading: "Yuklanmoqda…", updated: "Yangilangan", details: "Grafik ma'lumotlari", limited: "Muddat bo'yicha dastlabki 100 buyurtma.", noDeadline: "Belgilanmagan", newOrder: "Yangi buyurtma", finance: "Moliya · barcha davr", revenue: "Hisob-fakturalar", payments: "Olingan to'lovlar", financeError: "Moliya ma'lumotlari mavjud emas", total: "buyurtma", search: "Buyurtma qidirish", noStages: "Faol ishlab chiqarish buyurtmalari yo'q", from: "Dan", to: "Gacha",
  },
};
export type DashboardText = typeof messages.en;

export const statusNames: Record<keyof typeof messages, Record<string, string>> = {
  en: { new: "New", planning: "Planning", waiting_material: "Waiting for material", cutting: "Cutting", printing: "Printing", sewing: "Sewing", packaging: "Packaging", storage_transfer: "Storage transfer" },
  ru: { new: "Новый", planning: "Планирование", waiting_material: "Ожидание материала", cutting: "Раскрой", printing: "Печать", sewing: "Пошив", packaging: "Упаковка", storage_transfer: "Передача на склад" },
  uz: { new: "Yangi", planning: "Rejalashtirish", waiting_material: "Material kutilmoqda", cutting: "Bichish", printing: "Bosma", sewing: "Tikish", packaging: "Qadoqlash", storage_transfer: "Omborga topshirish" },
};

export const ledgerNote = {
  en: "Output uses stage records. Sewing daily reports and payroll are separate ledgers.",
  ru: "Выпуск по записям этапов. Ежедневные отчёты пошива и зарплата учитываются отдельно.",
  uz: "Natijalar bosqich yozuvlaridan olinadi. Kunlik tikish hisobotlari va ish haqi alohida hisoblanadi.",
};

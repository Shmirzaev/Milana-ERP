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

export const factoryText = {
  en: {
    all: "All factories", factory: "Factory", comparison: "Factory comparison",
    subtitle: "Production orders and recorded output", current: "Current orders", output: "Selected-period output, pcs",
    scope: "Orders follow sewing routing. Output belongs to the department that recorded the work.",
    shared: "Split orders appear in each involved factory; All factories counts each order once. Plans show the full order quantity.",
    unrouted: "Orders awaiting factory routing", unassigned: "Unassigned output remains in All factories.",
    finance: "Finance · all factories · all time", select: "Select factory", notRouted: "Not routed",
  },
  ru: {
    all: "Все фабрики", factory: "Фабрика", comparison: "Сравнение фабрик",
    subtitle: "Производственные заказы и учтённый выпуск", current: "Текущие заказы", output: "Выпуск за выбранный период, шт.",
    scope: "Заказы — по маршруту пошива. Выпуск относится к отделу, зарегистрировавшему работу.",
    shared: "Разделённый заказ виден на каждой участвующей фабрике, а в общем итоге считается один раз. План — полное количество заказа.",
    unrouted: "Заказы без маршрута фабрики", unassigned: "Выпуск без фабрики включён в общий итог.",
    finance: "Финансы · все фабрики · всё время", select: "Выбрать фабрику", notRouted: "Не назначена",
  },
  uz: {
    all: "Barcha fabrikalar", factory: "Fabrika", comparison: "Fabrikalarni taqqoslash",
    subtitle: "Ishlab chiqarish buyurtmalari va qayd etilgan natijalar", current: "Joriy buyurtmalar", output: "Tanlangan davrdagi natija, dona",
    scope: "Buyurtmalar tikish yo'nalishi bo'yicha. Natija ishni qayd etgan bo'limga tegishli.",
    shared: "Bo'lingan buyurtma har bir tegishli fabrikada ko'rinadi, umumiy hisobda bir marta sanaladi. Reja — buyurtmaning to'liq miqdori.",
    unrouted: "Fabrika yo'nalishi belgilanmagan buyurtmalar", unassigned: "Fabrikasi belgilanmagan natija umumiy hisobda qoladi.",
    finance: "Moliya · barcha fabrikalar · barcha davr", select: "Fabrikani tanlash", notRouted: "Belgilanmagan",
  },
};

export const activityText = {
  en: {
    exportReports: "Export sewing reports", reports: "Sewing reports", stages: "Stage records", title: "Daily sewing reports",
    description: "Reported pieces by factory · Tashkent business dates",
    note: "Daily reports are reported activity, not completed stage output. Quantities are not added together.",
    noOutput: "No output", empty: "No output recorded in this period.",
    more: "Show last 30 days", selected: "Selected day", source: "Chart source",
    period: "Period total", peak: "Peak day", noVisible: "Select a series to display.",
  },
  ru: {
    exportReports: "Экспорт отчётов пошива", reports: "Отчёты пошива", stages: "Записи этапов", title: "Ежедневные отчёты пошива",
    description: "Заявленный выпуск по фабрикам · даты Ташкента",
    note: "Ежедневные отчёты отражают заявленный выпуск, а не завершённый этап. Эти количества не суммируются.",
    noOutput: "Нет выпуска", empty: "За этот период выпуск не зарегистрирован.",
    more: "Показать последние 30 дней", selected: "Выбранный день", source: "Источник графика",
    period: "Итого за период", peak: "Максимум за день", noVisible: "Выберите ряд для отображения.",
  },
  uz: {
    exportReports: "Tikish hisobotlarini eksport qilish", reports: "Tikish hisobotlari", stages: "Bosqich yozuvlari", title: "Kunlik tikish hisobotlari",
    description: "Fabrikalar bo'yicha hisobotdagi dona · Toshkent sanalari",
    note: "Kunlik hisobot — qayd etilgan faoliyat, yakunlangan bosqich emas. Bu miqdorlar qo'shilmaydi.",
    noOutput: "Natija yo'q", empty: "Bu davrda natija qayd etilmagan.",
    more: "Oxirgi 30 kunni ko'rsatish", selected: "Tanlangan kun", source: "Grafik manbasi",
    period: "Davr jami", peak: "Kunlik eng yuqori", noVisible: "Ko'rsatish uchun qatorni tanlang.",
  },
};

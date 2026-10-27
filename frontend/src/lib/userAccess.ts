export type FactoryCode = "MIL" | "BST" | "ECO";
export type AccessPolicy = Partial<Record<FactoryCode, { allow: string[]; deny: string[] }>>;
export type AccessSubject = {
  name: string; email: string; role_id: number | null; department_id: number | null;
  factory_code: FactoryCode; extra_permissions?: string[];
};

export function changeAccess(policy: AccessPolicy | null, factory: FactoryCode, permission: string, state: "default" | "allow" | "deny"): AccessPolicy {
  const previous = policy?.[factory] ?? { allow: [], deny: [] };
  const next = { allow: previous.allow.filter((p) => p !== permission), deny: previous.deny.filter((p) => p !== permission) };
  if (state !== "default") next[state].push(permission);
  return { ...policy, [factory]: next };
}

const groups = {
  en: ["Sales", "Planning", "Models", "Cutting", "Printing", "Sewing", "Packaging", "Production", "Inventory", "Reservations", "Warehouse", "Purchasing", "Pricing", "Finance", "Payroll", "People", "Management", "Waste", "Usluga", "Administration"],
  ru: ["Продажи", "Планирование", "Модели", "Раскрой", "Печать", "Шитьё", "Упаковка", "Производство", "Запасы", "Резервы", "Склад", "Закупки", "Расчёт цены", "Финансы", "Зарплата", "Сотрудники", "Руководство", "Отходы", "Услуги", "Администрирование"],
  uz: ["Sotuv", "Rejalashtirish", "Modellar", "Bichish", "Bosma", "Tikuv", "Qadoqlash", "Ishlab chiqarish", "Zaxiralar", "Band qilish", "Ombor", "Xaridlar", "Narx hisoblash", "Moliya", "Ish haqi", "Xodimlar", "Rahbariyat", "Chiqindilar", "Usluga", "Boshqaruv"],
};
const texts = {
  en: { title: "Access settings", help: "Tick to give access; untick to remove it, including access from the role.", factory: "Access in factory", primary: "primary", search: "Find a permission", inherit: "Use default", allow: "Allow", deny: "Deny", allowed: "Allowed", blocked: "Not granted", factoryAvailable: "Factory login available", factoryUnavailable: "Allow a permission to enable this factory", overrides: "overrides", loading: "Checking access…", superOnly: "Only Super Admin can change access in another factory.", loadError: "Access could not be checked. Retry before saving.", noResults: "No matching permissions.", scopeHelp: "Permissions cover the actions named above. Shared lookup data may also be needed by other enabled workflows. Administrator-only operations and factory boundaries remain protected." },
  ru: { title: "Настройки доступа", help: "Отметьте, чтобы дать доступ; снимите отметку, чтобы убрать его, включая доступ роли.", factory: "Доступ на фабрике", primary: "основная", search: "Найти разрешение", inherit: "По умолчанию", allow: "Разрешить", deny: "Запретить", allowed: "Разрешено", blocked: "Не разрешено", factoryAvailable: "Вход на фабрику доступен", factoryUnavailable: "Разрешите доступ для входа на фабрику", overrides: "изменений", loading: "Проверка доступа…", superOnly: "Только суперадминистратор может менять доступ другой фабрики.", loadError: "Не удалось проверить доступ. Повторите перед сохранением.", noResults: "Разрешения не найдены.", scopeHelp: "Разрешения включают указанные действия. Общие справочники могут требоваться другим разрешённым процессам. Защита административных операций и границ фабрик сохраняется." },
  uz: { title: "Kirish sozlamalari", help: "Ruxsat berish uchun belgilang; ruxsatni, jumladan roldan olinganini, olib tashlash uchun belgini olib tashlang.", factory: "Fabrikadagi ruxsat", primary: "asosiy", search: "Ruxsatni qidirish", inherit: "Standart", allow: "Ruxsat berish", deny: "Taqiqlash", allowed: "Ruxsat bor", blocked: "Ruxsat yo‘q", factoryAvailable: "Fabrikaga kirish mumkin", factoryUnavailable: "Fabrikaga kirish uchun ruxsat bering", overrides: "o‘zgarish", loading: "Ruxsat tekshirilmoqda…", superOnly: "Boshqa fabrika ruxsatini faqat Super Admin o‘zgartira oladi.", loadError: "Ruxsatni tekshirib bo‘lmadi. Saqlashdan oldin qayta urinib ko‘ring.", noResults: "Ruxsatlar topilmadi.", scopeHelp: "Ruxsatlar yuqorida ko‘rsatilgan amallarni qamrab oladi. Umumiy ma’lumotlar boshqa ruxsat etilgan jarayonlarga ham kerak bo‘lishi mumkin. Administrator amallari va fabrika chegaralari himoyalangan." },
};
export function accessText(language: string) {
  const lang = language === "ru" || language === "uz" ? language : "en";
  return { ...texts[lang], groups: Object.fromEntries(groups.en.map((key, index) => [key, groups[lang][index]])) as Record<string, string> };
}

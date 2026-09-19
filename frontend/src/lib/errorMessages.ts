import type { Lang } from "./i18n/types";

export function errorDetail(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(errorDetail).filter(Boolean).join("; ");
  if (!value || typeof value !== "object") return "";
  const error = value as Record<string, unknown>;
  const message = errorDetail(error.detail) || errorDetail(error.message) || errorDetail(error.msg);
  if (!message) return "";
  const path = Array.isArray(error.loc)
    ? error.loc.filter((part) => part !== "body" && part !== "query" && part !== "path")
      .map((part) => typeof part === "number" ? `[${part + 1}]` : String(part).replaceAll("_", " "))
      .join(" / ")
    : "";
  return path ? `${path}: ${message}` : message;
}

// Raw server detail remains on ApiError for diagnostics; only localized text is rendered.
export function systemLanguage(): Lang {
  if (typeof document !== "undefined" && ["en", "ru", "uz"].includes(document.documentElement.lang)) return document.documentElement.lang as Lang;
  return "en";
}
const messages: Record<string, [string, string]> = {
  "Could not load HR data.": ["Не удалось загрузить данные отдела кадров.", "Kadrlar bo‘limi ma’lumotlarini yuklab bo‘lmadi."],
  "Select a brand for the production order.": ["Выберите бренд для производственного заказа.", "Ishlab chiqarish buyurtmasi uchun brendni tanlang."],
  "Select an available fabric batch for the cutting team.": ["Выберите доступную партию ткани для раскроя.", "Bichish uchun mavjud mato partiyasini tanlang."],
  "Enter estimated material amount greater than zero.": ["Укажите расчётный расход материала больше нуля.", "Hisoblangan mato sarfini noldan katta kiriting."],
  "Enter material estimate before creating the production order.": ["Перед созданием производственного заказа укажите расчётный расход материала.", "Ishlab chiqarish buyurtmasini yaratishdan oldin mato sarfini kiriting."],
  "Unable to load the variant price": ["Не удалось загрузить цену варианта.", "Variant narxini yuklab bo‘lmadi."],

  "No package items to create.": ["Нет изделий для создания упаковки.", "Qadoq yaratish uchun mahsulotlar yo‘q."],
  "Sign in before recording packages": ["Войдите в систему перед записью упаковок.", "Qadoqlarni qayd etishdan oldin tizimga kiring."],
  "Retry the saved package request before submitting changed values": ["Сначала повторите сохранённый запрос, затем изменяйте данные.", "Ma’lumotlarni o‘zgartirishdan oldin saqlangan so‘rovni qayta yuboring."],
  "The selected image could not be read": ["Не удалось прочитать выбранное изображение.", "Tanlangan rasmni o‘qib bo‘lmadi."],
  "The selected image could not be optimized": ["Не удалось обработать выбранное изображение.", "Tanlangan rasmni qayta ishlab bo‘lmadi."],
  "Image optimization is not available in this browser": ["Обработка изображений недоступна в этом браузере.", "Ushbu brauzerda rasmlarni qayta ishlash mavjud emas."],
  "Not authenticated": ["Войдите в систему снова.", "Tizimga qayta kiring."],
  "Invalid credentials": ["Неверный логин или пароль.", "Login yoki parol noto‘g‘ri."],
  "Incorrect email or password": ["Неверный логин или пароль.", "Login yoki parol noto‘g‘ri."],
  "Internal server error": ["Ошибка сервера. Повторите попытку позже.", "Server xatosi. Keyinroq qayta urinib ko‘ring."],
  "Failed to fetch": ["Нет связи с сервером. Проверьте подключение.", "Server bilan aloqa yo‘q. Ulanishni tekshiring."],
  "Network request failed": ["Нет связи с сервером. Проверьте подключение.", "Server bilan aloqa yo‘q. Ulanishni tekshiring."],
  "Request timed out": ["Сервер не ответил вовремя. Повторите попытку.", "Server vaqtida javob bermadi. Qayta urinib ko‘ring."],
  "Action failed.": ["Действие не выполнено. Повторите попытку.", "Amal bajarilmadi. Qayta urinib ko‘ring."],
  "Field required": ["Обязательное поле не заполнено.", "Majburiy maydon to‘ldirilmagan."],
  "Select a saved cutting passport for this order": ["Выберите сохранённый паспорт раскроя этого заказа.", "Ushbu buyurtmaning saqlangan bichish pasportini tanlang."],
  "This cutting passport has already been used. Open its cutting sheet or create a new passport": ["Этот паспорт раскроя уже использован. Откройте его лист раскроя или создайте новый паспорт.", "Bu bichish pasporti ishlatilgan. Uning bichish varag‘ini oching yoki yangi pasport yarating."],
  "Complete the material rows in the cutting passport before creating bundles": ["Перед созданием связок заполните материалы в паспорте раскроя.", "Bog‘lamlarni yaratishdan oldin bichish pasportidagi matolarni to‘ldiring."],
  "Correct the material quantities in the cutting passport": ["Исправьте количество материалов в паспорте раскроя.", "Bichish pasportidagi mato miqdorlarini tuzating."],
  "Enter the actual material amount in the cutting passport": ["Укажите фактический расход материала в паспорте раскроя.", "Bichish pasportida haqiqiy mato sarfini kiriting."],
  "Passport material usage requires a kilogram inventory batch": ["Для расхода по паспорту нужна партия ткани с единицей кг.", "Pasport bo‘yicha sarf uchun o‘lchov birligi kg bo‘lgan mato partiyasi kerak."],
  "The selected cutting passport does not belong to this order": ["Выбранный паспорт раскроя относится к другому заказу.", "Tanlangan bichish pasporti boshqa buyurtmaga tegishli."],
  "Enter the actual amount used for every planned fabric before creating bundles": ["Перед созданием связок укажите расход каждой запланированной ткани в паспорте раскроя.", "Bog‘lamlardan oldin har bir rejalashtirilgan matoning sarfini bichish pasportiga kiriting."],
  "Cutting materials must match the fabrics selected in planning": ["Материалы раскроя должны совпадать с тканями из планирования.", "Bichish matolari rejalashtirishda tanlangan matolarga mos bo‘lishi kerak."],
  "The same fabric batch cannot be consumed more than once": ["Одна партия ткани не может повторяться в расходе.", "Bir mato partiyasi sarfda takrorlanmasligi kerak."],
  "Passed and defective pieces cannot exceed cut pieces": ["Годных и дефектных изделий не может быть больше, чем раскроено.", "Yaroqli va nuqsonli mahsulotlar bichilgan miqdordan oshmasligi kerak."],
  "Package is not attached to this shipment": ["Упаковка не добавлена в эту отгрузку.", "Qadoq ushbu jo‘natmaga qo‘shilmagan."],
  "Package is no longer in storage": ["Упаковка больше не находится на складе.", "Qadoq endi omborda emas."],
  "Remove packages before dispatch with a reason": ["Упаковку можно убрать до отгрузки, указав причину.", "Qadoqni jo‘natishdan oldin sababini ko‘rsatib olib tashlash mumkin."],
  "Reservation no longer matches warehouse stock": ["Резерв не совпадает с остатком на складе. Обновите данные.", "Band qilingan miqdor ombor qoldig‘iga mos emas. Ma’lumotlarni yangilang."],
  "All requested packages for this model are already scanned": ["Все заказанные упаковки этой модели уже отсканированы.", "Ushbu modelning barcha buyurtma qadoqlari skanerlangan."],
  "Package not found. Please scan the correct package label.": ["Упаковка не найдена. Отсканируйте правильную этикетку.", "Qadoq topilmadi. To‘g‘ri yorliqni skanerlang."],
  "Package contents and warehouse stock do not match": ["Содержимое упаковки не совпадает с остатком на складе.", "Qadoq tarkibi ombor qoldig‘iga mos kelmaydi."],
  "Stock/reservation quantities do not balance": ["Количество на складе и в резерве не совпадает.", "Ombor va band qilingan miqdorlar mos emas."],
  "Package quantity changed; reload before correcting": ["Количество в упаковке изменилось. Обновите данные перед исправлением.", "Qadoq miqdori o‘zgargan. Tuzatishdan oldin ma’lumotlarni yangilang."],
  "A correction reason is required": ["Укажите причину исправления.", "Tuzatish sababini kiriting."],
  "Shipment not found": ["Отгрузка не найдена.", "Jo‘natma topilmadi."],
  "Package not found": ["Упаковка не найдена.", "Qadoq topilmadi."],
  "Work order not found": ["Производственное задание не найдено.", "Ish topshirig‘i topilmadi."],
  "Production order not found": ["Производственный заказ не найден.", "Ishlab chiqarish buyurtmasi topilmadi."],
  "Insufficient stock": ["Недостаточно товара на складе.", "Omborda yetarli mahsulot yo‘q."],
  "Insufficient available stock": ["Недостаточно свободного остатка на складе.", "Omborda yetarli bo‘sh qoldiq yo‘q."],
  "Conflicting bundle references": ["Номер связки и штрихкод не совпадают.", "Bog‘lam raqami va shtrix-kod mos kelmaydi."],
};
const fallback: Record<Lang, Record<string, string>> = {
  en: { default: "The action could not be completed.", "400": "Check the entered data.", "401": "Please sign in again.", "403": "You do not have permission for this action.", "404": "The requested record was not found.", "409": "The record cannot be changed in its current state. Refresh and check linked records.", "422": "Check the required fields and entered values.", "429": "Too many requests. Please try again shortly.", server: "The server could not complete the request. Try again later." },
  ru: { default: "Не удалось выполнить действие.", "400": "Проверьте введённые данные.", "401": "Войдите в систему снова.", "403": "У вас нет доступа к этому действию.", "404": "Запись не найдена.", "409": "Текущее состояние записи не позволяет выполнить действие. Обновите данные и проверьте связанные записи.", "422": "Проверьте обязательные поля и введённые значения.", "429": "Слишком много запросов. Повторите попытку позже.", server: "Сервер не смог выполнить запрос. Повторите попытку позже." },
  uz: { default: "Amalni bajarib bo‘lmadi.", "400": "Kiritilgan ma’lumotlarni tekshiring.", "401": "Tizimga qayta kiring.", "403": "Ushbu amal uchun ruxsatingiz yo‘q.", "404": "Yozuv topilmadi.", "409": "Yozuvning joriy holati ushbu amalni bajarishga yo‘l qo‘ymaydi. Ma’lumotlar va bog‘langan yozuvlarni tekshiring.", "422": "Majburiy maydonlar va kiritilgan qiymatlarni tekshiring.", "429": "So‘rovlar juda ko‘p. Keyinroq qayta urinib ko‘ring.", server: "Server so‘rovni bajara olmadi. Keyinroq qayta urinib ko‘ring." },
};
const workflowErrors: Record<string, Record<"en" | "ru" | "uz", string>> = {
  FIRST_GRADE_VARIANT_EVIDENCE: { en: "Select the production model and color. Singles require a production order with one verified color.", ru: "Выберите модель и цвет производства. Для поштучных изделий нужен заказ с одним подтверждённым цветом.", uz: "Ishlab chiqarish modeli va rangini tanlang. Donalab mahsulot uchun bitta tasdiqlangan rangli buyurtma kerak." },
  FIRST_GRADE_SIZE_EVIDENCE_REQUIRED: { en: "Record the accepted sewing quantities by size before allocating singles.", ru: "Перед выделением поштучных изделий укажите принятые из пошива количества по размерам.", uz: "Donalab ajratishdan oldin tikuvdan qabul qilingan miqdorlarni o‘lcham bo‘yicha kiriting." },
  FIRST_GRADE_SIZE_EXCEEDED: { en: "This size exceeds the remaining accepted sewing quantity. Refresh the balance.", ru: "Количество этого размера превышает остаток принятого пошива. Обновите остатки.", uz: "Ushbu o‘lcham miqdori qabul qilingan tikuv qoldig‘idan oshdi. Qoldiqni yangilang." },
  FIRST_GRADE_MIXED_BATCH_EVIDENCE: { en: "Allocate one batch at a time. Existing mixed-batch packs need a verified size breakdown first.", ru: "Распределяйте одну партию за раз. Для смешанных упаковок сначала нужен подтверждённый состав по размерам.", uz: "Bir vaqtning o‘zida bitta partiyani ajrating. Aralash partiyali qadoqlar uchun tasdiqlangan o‘lcham tarkibi kerak." },
  FIRST_GRADE_ONE_PIECE_REQUIRED: { en: "Each First Grade package must contain exactly one piece.", ru: "Каждая упаковка 1-го сорта должна содержать одно изделие.", uz: "Har bir 1-nav qadog‘ida aynan bitta dona bo‘lishi kerak." },
  FIRST_GRADE_CONTENTS_IMMUTABLE: { en: "The size, batch and quantity of a First Grade single cannot be changed.", ru: "Размер, партию и количество поштучного изделия менять нельзя.", uz: "Donalab mahsulotning o‘lchami, partiyasi va miqdorini o‘zgartirib bo‘lmaydi." },
  FIRST_GRADE_CUSTOMER_OWNED: { en: "Customer-owned production cannot be moved into free First Grade stock.", ru: "Продукцию клиентского заказа нельзя перевести в свободный остаток 1-го сорта.", uz: "Mijoz buyurtmasi mahsulotini erkin 1-nav qoldig‘iga o‘tkazib bo‘lmaydi." },
  FIRST_GRADE_SEPARATE_ORDER: { en: "Use a separate First Grade sale with exact sizes and piece quantities.", ru: "Создайте отдельную продажу 1-го сорта с точными размерами и количеством изделий.", uz: "Aniq o‘lchamlar va dona miqdorlari bilan alohida 1-nav sotuvini yarating." },
  SHIPMENT_DELETE_BEFORE_DISPATCH: { en: "Only an undispatched manual shipment can be deleted.", ru: "Удалить можно только ещё не отправленную ручную отгрузку.", uz: "Faqat hali yuborilmagan qo‘lda yaratilgan jo‘natmani o‘chirish mumkin." },
  SHIPMENT_ALREADY_DELETED: { en: "This shipment was deleted. Start a new shipment if needed.", ru: "Эта отгрузка удалена. При необходимости создайте новую.", uz: "Bu jo‘natma o‘chirilgan. Kerak bo‘lsa yangi jo‘natma yarating." },
};

export function localizeError(detail: string, status = 0, lang = systemLanguage()): string {
  if (workflowErrors[detail]) return workflowErrors[detail][lang];
  if (lang === "en") return detail || fallback.en[String(status)] || fallback.en.default!;
  const index = lang === "ru" ? 0 : 1;
  const plain = detail.replace(/^\d{3}:\s*/, "").trim();
  if (messages[plain]) return messages[plain][index];
  const match = plain.match(/^Package (.+) (belongs to another sales order\.|is already attached to shipment (.+)\.|was already scanned for this shipment\.)$/);
  if (match) {
    if (match[2]!.startsWith("belongs")) return lang === "ru" ? `Упаковка ${match[1]} относится к другому заказу.` : `${match[1]} qadoq boshqa buyurtmaga tegishli.`;
    if (match[3]) return lang === "ru" ? `Упаковка ${match[1]} уже добавлена в отгрузку ${match[3]}.` : `${match[1]} qadoq ${match[3]} jo‘natmasiga qo‘shilgan.`;
    return lang === "ru" ? `Упаковка ${match[1]} уже отсканирована.` : `${match[1]} qadoq allaqachon skanerlangan.`;
  }
  return fallback[lang][status >= 500 ? "server" : String(status)] || fallback[lang].default!;
}
export class ApiError extends Error {
  public rawDetail: string;
  constructor(public status: number, detail: unknown) {
    const rawDetail = errorDetail(detail);
    super(`${status ? `${status}: ` : ""}${localizeError(rawDetail, status)}`);
    this.rawDetail = rawDetail;
    this.name = "ApiError";
  }
}

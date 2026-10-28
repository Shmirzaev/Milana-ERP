const en = {
  packCount: "Number of packs",
  scanTotals: "Choose how many packs to sell. Warehouse scans confirm the pieces; the warehouse confirms the invoice amount.",
  warehouseConfirms: "Confirmed by warehouse",
  duplicateVariant: "Use one line per model variant and enter the total number of packs.",
  insufficientPacks: "Not enough complete packs",
  stockLoadFailed: "Could not load available packs. Please try again.",
};

const ru: typeof en = {
  packCount: "Количество упаковок",
  scanTotals: "Укажите количество упаковок для продажи. Склад определит количество изделий по сканам и подтвердит сумму накладной.",
  warehouseConfirms: "Подтверждает склад",
  duplicateVariant: "Для каждого варианта модели используйте одну строку с общим количеством упаковок.",
  insufficientPacks: "Недостаточно целых упаковок",
  stockLoadFailed: "Не удалось загрузить доступные упаковки. Повторите попытку.",
};

const uz: typeof en = {
  packCount: "Qadoqlar soni",
  scanTotals: "Sotiladigan qadoqlar sonini kiriting. Ombor skanlar orqali dona sonini aniqlaydi va yuk xati summasini tasdiqlaydi.",
  warehouseConfirms: "Ombor tasdiqlaydi",
  duplicateVariant: "Har bir model varianti uchun bitta qatorda jami qadoqlar sonini kiriting.",
  insufficientPacks: "Butun qadoqlar yetarli emas",
  stockLoadFailed: "Mavjud qadoqlarni yuklab bo‘lmadi. Qayta urinib ko‘ring.",
};

export function readySalesText(language: string): typeof en {
  return language === "ru" ? ru : language === "uz" ? uz : en;
}

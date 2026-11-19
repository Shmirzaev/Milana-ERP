export enum CuttingDepartmentCode {
  Milana = "CUT",
  EcoCotton = "ECT",
}

export type CuttingFactoryOptions = {
  production_order_id: number;
  cutting_department_code: CuttingDepartmentCode;
  available_departments: CuttingDepartmentCode[];
  can_change: boolean;
  lock_reason: keyof typeof cuttingFactoryMessages.en.reasons | null;
  changed: boolean;
};

export const cuttingFactoryNames: Record<CuttingDepartmentCode, string> = {
  CUT: "Milana",
  ECT: "Eco Cotton",
};

export const cuttingFactoryMessages = {
  en: {
    title: "Change cutting factory", order: "Production order", current: "Current cutting factory",
    destination: "New cutting factory", choose: "Select an order", selectFactory: "Select a factory",
    help: "Available before cutting or downstream work is recorded. Sewing and packaging plans stay unchanged.",
    saved: "Cutting factory updated.", error: "Could not load or update the cutting factory. Refresh and try again.",
    refreshError: "The change was saved. Refresh to load the latest order information.",
    reasons: {
      CUTTING_FACTORY_ORDER_LOCKED: "This order is closed, has advanced beyond Cutting, or uses a separate service workflow.",
      CUTTING_FACTORY_HISTORY_LOCKED: "Cutting or downstream work has been recorded. The cutting factory cannot be changed.",
      CUTTING_FACTORY_ROUTING_LOCKED: "This order has no single supported cutting route. Ask the production supervisor to review it.",
      CUTTING_FACTORY_ASSIGNMENT_LOCKED: "A cutting operator is assigned. Review the assignment before changing the factory.",
      CUTTING_FACTORY_DESTINATION_DENIED: "Planning access is required in both the current and new factories.",
      CUTTING_FACTORY_BUSY: "This order is being updated. Refresh and try again.",
    },
  },
  ru: {
    title: "Изменить фабрику раскроя", order: "Производственный заказ", current: "Текущая фабрика раскроя",
    destination: "Новая фабрика раскроя", choose: "Выберите заказ", selectFactory: "Выберите фабрику",
    help: "Доступно до регистрации раскроя или последующих работ. Планы пошива и упаковки сохраняются.",
    saved: "Фабрика раскроя изменена.", error: "Не удалось загрузить или изменить фабрику раскроя. Обновите и повторите попытку.",
    refreshError: "Изменение сохранено. Обновите данные заказа.",
    reasons: {
      CUTTING_FACTORY_ORDER_LOCKED: "Заказ закрыт, перешёл дальше раскроя или относится к отдельному процессу услуг.",
      CUTTING_FACTORY_HISTORY_LOCKED: "Раскрой или последующие работы уже зарегистрированы. Фабрику раскроя изменить нельзя.",
      CUTTING_FACTORY_ROUTING_LOCKED: "У заказа нет единого поддерживаемого маршрута раскроя. Обратитесь к руководителю производства.",
      CUTTING_FACTORY_ASSIGNMENT_LOCKED: "Назначен оператор раскроя. Проверьте назначение перед сменой фабрики.",
      CUTTING_FACTORY_DESTINATION_DENIED: "Необходим доступ к планированию на текущей и новой фабриках.",
      CUTTING_FACTORY_BUSY: "Заказ обновляется. Обновите и повторите попытку.",
    },
  },
  uz: {
    title: "Bichish fabrikasini o‘zgartirish", order: "Ishlab chiqarish buyurtmasi", current: "Joriy bichish fabrikasi",
    destination: "Yangi bichish fabrikasi", choose: "Buyurtmani tanlang", selectFactory: "Fabrikani tanlang",
    help: "Bichish yoki keyingi ishlar qayd etilguncha mavjud. Tikuv va qadoqlash rejalari saqlanadi.",
    saved: "Bichish fabrikasi o‘zgartirildi.", error: "Bichish fabrikasini yuklash yoki o‘zgartirish imkoni bo‘lmadi. Yangilab, qayta urinib ko‘ring.",
    refreshError: "O‘zgarish saqlandi. Buyurtmaning so‘nggi ma’lumotlarini yuklash uchun yangilang.",
    reasons: {
      CUTTING_FACTORY_ORDER_LOCKED: "Buyurtma yopilgan, bichishdan keyingi bosqichga o‘tgan yoki alohida xizmat jarayoniga tegishli.",
      CUTTING_FACTORY_HISTORY_LOCKED: "Bichish yoki keyingi ishlar qayd etilgan. Bichish fabrikasini o‘zgartirib bo‘lmaydi.",
      CUTTING_FACTORY_ROUTING_LOCKED: "Buyurtmada yagona qo‘llab-quvvatlanadigan bichish yo‘nalishi yo‘q. Ishlab chiqarish rahbariga murojaat qiling.",
      CUTTING_FACTORY_ASSIGNMENT_LOCKED: "Bichish operatori tayinlangan. Fabrikani o‘zgartirishdan oldin tayinlovni tekshiring.",
      CUTTING_FACTORY_DESTINATION_DENIED: "Joriy va yangi fabrikalarda rejalashtirish huquqi kerak.",
      CUTTING_FACTORY_BUSY: "Buyurtma yangilanmoqda. Yangilab, qayta urinib ko‘ring.",
    },
  },
};

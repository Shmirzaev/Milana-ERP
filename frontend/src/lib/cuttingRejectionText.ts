export const cuttingRejectionText = {
  en: {
    action: "Reject order", title: "Reject Cutting order", reason: "Rejection reason",
    hint: "Planning will be notified. Only orders without recorded Cutting output or downstream work can be rejected.",
    required: "Enter a rejection reason.", saved: "Order rejected", cancel: "Cancel",
  },
  ru: {
    action: "Отклонить заказ", title: "Отклонить заказ раскроя", reason: "Причина отклонения",
    hint: "Планирование получит уведомление. Можно отклонить только заказ без результатов раскроя и последующих работ.",
    required: "Укажите причину отклонения.", saved: "Заказ отклонён", cancel: "Отмена",
  },
  uz: {
    action: "Buyurtmani rad etish", title: "Bichuv buyurtmasini rad etish", reason: "Rad etish sababi",
    hint: "Rejalashtirishga xabar yuboriladi. Faqat bichuv natijasi va keyingi ishlar qayd etilmagan buyurtmani rad etish mumkin.",
    required: "Rad etish sababini kiriting.", saved: "Buyurtma rad etildi", cancel: "Bekor qilish",
  },
} as const;

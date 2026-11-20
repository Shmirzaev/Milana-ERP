export const cuttingHandoffText = {
  en: {
    stock: "Bundle storage by order", handoff: "Cutting to Sewing", order: "Order", nastil: "Nastil",
    destination: "Destination", send: "Send to Sewing", dispatched: "Nastil sent to Sewing.",
    choose: "Select a Nastil", search: "Search order or Nastil", inTransit: "In transit",
    daily: "Daily dispatches", reportDate: "Dispatch date (Tashkent)", download: "Download CSV",
    sent: "Sent to Sewing", accepted: "Accepted by Sewing", pieces: "Pieces",
    emptyStock: "No orders in bundle storage.", emptyPending: "No Nastils are in transit.",
    emptyDaily: "No dispatches on this date.", more: "Show more orders", fewer: "Show fewer orders",
  },
  ru: {
    stock: "Склад кроя по заказам", handoff: "Передача из раскроя в пошив", order: "Заказ", nastil: "Настил",
    destination: "Назначение", send: "Отправить в пошив", dispatched: "Настил отправлен в пошив.",
    choose: "Выберите настил", search: "Поиск заказа или настила", inTransit: "В пути",
    daily: "Отправки за день", reportDate: "Дата отправки (Ташкент)", download: "Скачать CSV",
    sent: "Отправлено в пошив", accepted: "Принято пошивом", pieces: "Изделия",
    emptyStock: "На складе кроя нет заказов.", emptyPending: "Нет настилов в пути.",
    emptyDaily: "На эту дату отправок нет.", more: "Показать ещё заказы", fewer: "Свернуть список",
  },
  uz: {
    stock: "Bichim ombori buyurtmalar bo‘yicha", handoff: "Bichimdan tikuvga topshirish", order: "Buyurtma", nastil: "Nastil",
    destination: "Qabul qiluvchi", send: "Tikuvga jo‘natish", dispatched: "Nastil tikuvga jo‘natildi.",
    choose: "Nastilni tanlang", search: "Buyurtma yoki nastilni qidiring", inTransit: "Yo‘lda",
    daily: "Kunlik jo‘natmalar", reportDate: "Jo‘natish sanasi (Toshkent)", download: "CSV yuklab olish",
    sent: "Tikuvga jo‘natildi", accepted: "Tikuv qabul qildi", pieces: "Dona",
    emptyStock: "Bichim omborida buyurtmalar yo‘q.", emptyPending: "Yo‘lda nastillar yo‘q.",
    emptyDaily: "Bu sanada jo‘natmalar yo‘q.", more: "Ko‘proq buyurtma ko‘rsatish", fewer: "Ro‘yxatni yig‘ish",
  },
};

export type HandoffFactory = "BST" | "MIL";
export const handoffFactoryName: Record<HandoffFactory, string> = { BST: "Besttex", MIL: "Milana" };

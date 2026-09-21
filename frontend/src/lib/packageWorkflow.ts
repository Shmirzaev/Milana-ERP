import { api } from "@/lib/api";
import type { Lang } from "@/lib/i18n";

const en = {
  packQuantity: "Quantity in pack", deletePacks: "Delete mistaken packs", deleteConfirm: "Delete selected packs? Available stock is removed. Shipped labels are retired; shipment and client accounting history stay saved.",
  manual: "Record physical warehouse packs", model: "Model / variant", color: "Color",
  weight: "Weight per pack (kg)", count: "Number of packs", sizes: "Size quantities per pack",
  reason: "Receipt reference / reason", save: "Record receipt and create labels", cancel: "Cancel",
  received: "Warehouse receipt recorded", runs: "Print runs", reprint: "Reprint labels",
  empty: "No print runs yet", loading: "Loading…", more: "Load more", none: "No models found",
  packages: "Packages", pieces: "Pieces", status: "Receipt", pending: "Awaiting warehouse",
  complete: "Received", scanHint: "Scan any package QR in a print run to receive exactly that run's packages in one scan.",
  runReceived: "Print run received", printSelected: "Reprint selected packages", retry: "Retry the same receipt",
  review: "This records physical stock already in the warehouse. Check the model and quantity in each pack before saving.",
  createRun: "Create receiving print run from selected", select: "Select", size: "Size", quantity: "Quantity",
  pendingRequest: "The previous request has not been confirmed. Retry the saved request before recording another receipt.",
  cancelPending: "Cancel or recover the pending receipt", pendingCancelled: "The pending request was safely cancelled. Correct the values and submit again.",
};
type Copy = Record<keyof typeof en, string>;
const ru: Copy = {
  packQuantity: "Количество в упаковке", deletePacks: "Удалить ошибочные упаковки", deleteConfirm: "Удалить выбранные упаковки? Доступный остаток удаляется. Отгруженные этикетки скрываются; история отгрузки и расчётов клиента сохраняется.",
  manual: "Оприходовать физические упаковки", model: "Модель / вариант", color: "Цвет",
  weight: "Вес одной упаковки (кг)", count: "Количество упаковок", sizes: "Размеры и количество в одной упаковке",
  reason: "Основание / документ прихода", save: "Оприходовать и создать этикетки", cancel: "Отмена",
  received: "Приход на склад сохранён", runs: "Группы печати", reprint: "Повторная печать",
  empty: "Групп печати пока нет", loading: "Загрузка…", more: "Загрузить ещё", none: "Модели не найдены",
  packages: "Упаковки", pieces: "Изделия", status: "Приёмка", pending: "Ожидает склада",
  complete: "Принято", scanHint: "Отсканируйте QR любой упаковки группы печати, чтобы принять только эту группу одним сканированием.",
  runReceived: "Группа печати принята", printSelected: "Перепечатать выбранные упаковки", retry: "Повторить тот же приход",
  review: "Это приход фактически находящегося на складе товара. Перед сохранением проверьте модель, размеры, количество изделий и упаковок.",
  createRun: "Создать группу приёмки из выбранных", select: "Выбрать", size: "Размер", quantity: "Количество",
  pendingRequest: "Предыдущий запрос не подтверждён. Повторите сохранённый запрос перед новым приходом.",
  cancelPending: "Отменить или восстановить ожидающий приход", pendingCancelled: "Ожидающий запрос безопасно отменён. Исправьте данные и отправьте снова.",
};
const uz: Copy = {
  packQuantity: "Qadoqdagi miqdor", deletePacks: "Xato qadoqlarni o‘chirish", deleteConfirm: "Tanlangan qadoqlar o‘chirilsinmi? Mavjud qoldiq o‘chiriladi. Jo‘natilgan yorliqlar yashiriladi; jo‘natma va mijoz hisob-kitob tarixi saqlanadi.",
  manual: "Ombordagi haqiqiy qadoqlarni kirim qilish", model: "Model / variant", color: "Rang",
  weight: "Bitta qadoq vazni (kg)", count: "Qadoqlar soni", sizes: "Bitta qadoqdagi o‘lchamlar va miqdor",
  reason: "Kirim hujjati / sababi", save: "Kirim qilish va yorliqlar yaratish", cancel: "Bekor qilish",
  received: "Ombor kirimi saqlandi", runs: "Chop etish guruhlari", reprint: "Yorliqlarni qayta chop etish",
  empty: "Chop etish guruhlari yo‘q", loading: "Yuklanmoqda…", more: "Yana yuklash", none: "Modellar topilmadi",
  packages: "Qadoqlar", pieces: "Dona", status: "Qabul", pending: "Ombor qabulini kutmoqda",
  complete: "Qabul qilindi", scanHint: "Guruhdagi istalgan qadoq QR kodini bir marta skanerlab, faqat shu guruh qadoqlarini qabul qiling.",
  runReceived: "Chop etish guruhi qabul qilindi", printSelected: "Tanlangan qadoqlarni qayta chop etish", retry: "Shu kirimni qayta yuborish",
  review: "Bu omborda mavjud haqiqiy mahsulot kirimidir. Saqlashdan oldin model, o‘lchamlar, dona va qadoqlar sonini tekshiring.",
  createRun: "Tanlanganlardan qabul guruhini yaratish", select: "Tanlash", size: "O‘lcham", quantity: "Miqdor",
  pendingRequest: "Oldingi so‘rov tasdiqlanmagan. Yangi kirimdan oldin saqlangan so‘rovni qayta yuboring.",
  cancelPending: "Kutilayotgan kirimni bekor qilish yoki tiklash", pendingCancelled: "Kutilayotgan so‘rov xavfsiz bekor qilindi. Ma’lumotlarni tuzatib, qayta yuboring.",
};
export const packageWorkflowCopy: Record<Lang, Copy> = { en, ru, uz };

export type PackagePrintRun = {
  id: number; run_no: string; code: string; count: number; quantity: number;
  manual_receipt?: boolean;
  packages: Array<{ id: number; package_no: string; quantity: number }>;
  package_ids: number[]; created_at: string; received_at: string | null;
};

type PendingPackageRequest = { requestKey: string; body: Record<string, any> };
function notifyPackageWorkflowChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("package-request-changed"));
}

function clearPendingPackageWorkflow(storageKey: string, requestKey: string): boolean {
  const saved = sessionStorage.getItem(storageKey);
  if (!saved || JSON.parse(saved).requestKey !== requestKey) return false;
  sessionStorage.removeItem(storageKey);
  notifyPackageWorkflowChanged();
  return true;
}

export function pendingPackageWorkflow(path: string, userId: number): PendingPackageRequest | null {
  const saved = sessionStorage.getItem(`package-request:${userId}:${path}`);
  return saved ? JSON.parse(saved) : null;
}

// Preserve BOTH identity and payload through uncertain responses/reload. Edits
// cannot turn a lost response into an accidental second physical-stock receipt.
export async function postPackageWorkflow<T>(path: string, body: unknown, userId: number): Promise<T> {
  if (!userId) throw new Error("Sign in before recording packages");
  const storageKey = `package-request:${userId}:${path}`;
  let pending = pendingPackageWorkflow(path, userId);
  const wasPending = !!pending;
  if (pending && JSON.stringify(pending.body) !== JSON.stringify(body)) {
    throw new Error("Retry the saved package request before submitting changed values");
  }
  if (!pending) {
    pending = { requestKey: crypto.randomUUID(), body: body as Record<string, any> };
    sessionStorage.setItem(storageKey, JSON.stringify(pending));
    notifyPackageWorkflowChanged();
  }
  try {
    const result = await api.post<T>(path, { ...pending.body, request_key: pending.requestKey }, 60_000);
    if (!clearPendingPackageWorkflow(storageKey, pending.requestKey)) {
      const newer = pendingPackageWorkflow(path, userId);
      if (newer && newer.requestKey !== pending.requestKey) {
        throw new Error("A newer pending package request is active; retry that saved request");
      }
    }
    return result;
  } catch (error: any) {
    // A definite first rejection can be corrected. Once an earlier outcome is
    // uncertain, even a later permission/rate-limit error cannot prove it failed.
    if (!wasPending && /^(400|401|403|404|409|422|429):/.test(String(error?.message))) {
      clearPendingPackageWorkflow(storageKey, pending.requestKey);
    }
    throw error;
  }
}

export type PackageWorkflowReconciliation<T> =
  | { status: "completed"; result: T }
  | { status: "cancelled" };

export async function reconcilePendingPackageWorkflow<T>(
  path: string,
  userId: number,
): Promise<PackageWorkflowReconciliation<T>> {
  if (!userId) throw new Error("Sign in before reconciling packages");
  if (path !== "/api/packages/manual-receipt") throw new Error("Only manual receipts support reconciliation");
  const storageKey = `package-request:${userId}:${path}`;
  const pending = pendingPackageWorkflow(path, userId);
  if (!pending) throw new Error("No pending package request to reconcile");
  const result = await api.post<PackageWorkflowReconciliation<T>>(
    `${path}/reconcile`,
    { ...pending.body, request_key: pending.requestKey },
    60_000,
  );
  if (!result || (result.status !== "completed" && result.status !== "cancelled") ||
      (result.status === "completed" && (!("result" in result) || result.result == null))) {
    throw new Error("Package request reconciliation returned an invalid status");
  }
  if (!clearPendingPackageWorkflow(storageKey, pending.requestKey)) {
    const newer = pendingPackageWorkflow(path, userId);
    if (newer && newer.requestKey !== pending.requestKey) {
      throw new Error("A newer pending package request is active; retry that saved request");
    }
  }
  return result;
}

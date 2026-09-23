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
  runReceived: "Print run received", printSelected: "Reprint selected packages", retry: "Retry the same receipt", recover: "Recover saved request",
  review: "This records physical stock already in the warehouse. Check the model and quantity in each pack before saving.",
  createRun: "Create receiving print run from selected", select: "Select", size: "Size", quantity: "Quantity",
  pendingRequest: "The previous request has not been confirmed. Retry the saved request before recording another receipt.",
  cancelPending: "Cancel or recover the pending receipt", pendingCancelled: "The pending request was safely cancelled. Correct the values and submit again.", resultUnavailable: "The request was completed, but its result is deleted or no longer available with your access. Saved retry data was cleared safely.", labelUnavailable: "The receipt was saved, but its label is unavailable. Refresh or ask a manager to restore access before retrying the label.",
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
  runReceived: "Группа печати принята", printSelected: "Перепечатать выбранные упаковки", retry: "Повторить тот же приход", recover: "Восстановить сохранённый запрос",
  review: "Это приход фактически находящегося на складе товара. Перед сохранением проверьте модель, размеры, количество изделий и упаковок.",
  createRun: "Создать группу приёмки из выбранных", select: "Выбрать", size: "Размер", quantity: "Количество",
  pendingRequest: "Предыдущий запрос не подтверждён. Повторите сохранённый запрос перед новым приходом.",
  cancelPending: "Отменить или восстановить ожидающий приход", pendingCancelled: "Ожидающий запрос безопасно отменён. Исправьте данные и отправьте снова.", resultUnavailable: "Запрос выполнен, но результат удалён или недоступен с текущими правами. Сохранённые данные повтора безопасно очищены.", labelUnavailable: "Приход сохранён, но этикетка недоступна. Обновите страницу или попросите менеджера восстановить доступ перед повторной печатью.",
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
  runReceived: "Chop etish guruhi qabul qilindi", printSelected: "Tanlangan qadoqlarni qayta chop etish", retry: "Shu kirimni qayta yuborish", recover: "Saqlangan so‘rovni tiklash",
  review: "Bu omborda mavjud haqiqiy mahsulot kirimidir. Saqlashdan oldin model, o‘lchamlar, dona va qadoqlar sonini tekshiring.",
  createRun: "Tanlanganlardan qabul guruhini yaratish", select: "Tanlash", size: "O‘lcham", quantity: "Miqdor",
  pendingRequest: "Oldingi so‘rov tasdiqlanmagan. Yangi kirimdan oldin saqlangan so‘rovni qayta yuboring.",
  cancelPending: "Kutilayotgan kirimni bekor qilish yoki tiklash", pendingCancelled: "Kutilayotgan so‘rov xavfsiz bekor qilindi. Ma’lumotlarni tuzatib, qayta yuboring.", resultUnavailable: "So‘rov bajarilgan, ammo natija o‘chirilgan yoki joriy ruxsat bilan mavjud emas. Saqlangan takrorlash ma’lumotlari xavfsiz tozalandi.", labelUnavailable: "Kirim saqlandi, ammo yorliq mavjud emas. Sahifani yangilang yoki qayta chop etishdan oldin menejerdan ruxsatni tiklashni so‘rang.",
};
export const packageWorkflowCopy: Record<Lang, Copy> = { en, ru, uz };

export type PackagePrintRun = {
  id: number; run_no: string; code: string; count: number; quantity: number;
  manual_receipt?: boolean;
  packages: Array<{ id: number; package_no: string; quantity: number }>;
  package_ids: number[]; created_at: string; received_at: string | null;
};

type PendingPackageRequest = { requestKey: string; body: Record<string, any> };
type PackageRequestStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export const packageWorkflowChangedEvent = "package-request-changed";

function notifyPackageWorkflowChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(packageWorkflowChangedEvent));
}

export function packageWorkflowStorageKey(path: string, userId: number): string {
  return `package-request:${userId}:${path}`;
}

function requirePackageWorkflowStorage(): {
  current: PackageRequestStorage;
  legacy: PackageRequestStorage;
} {
  if (typeof window === "undefined") throw new Error("Package recovery storage is unavailable");
  try {
    return { current: window.localStorage, legacy: window.sessionStorage };
  } catch {
    throw new Error("Package recovery storage is unavailable");
  }
}

function parsePendingPackageRequest(raw: string | null): PendingPackageRequest | null {
  if (!raw) return null;
  try {
    const pending = JSON.parse(raw) as PendingPackageRequest;
    if (!pending || typeof pending !== "object"
      || typeof pending.requestKey !== "string"
      || !/^[A-Za-z0-9._:-]{1,128}$/.test(pending.requestKey)
      || !pending.body || typeof pending.body !== "object" || Array.isArray(pending.body)) {
      throw new Error("Invalid saved package request");
    }
    return pending;
  } catch {
    // Never replace unreadable evidence with a new key: the old request may
    // already have committed even if this browser cannot deserialize it.
    throw new Error("Saved package recovery data is invalid; do not submit another request");
  }
}

function readPendingFromStorage(
  storage: PackageRequestStorage,
  storageKey: string,
): PendingPackageRequest | null {
  try {
    return parsePendingPackageRequest(storage.getItem(storageKey));
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("Saved package recovery")) throw error;
    throw new Error("Package recovery storage is unavailable");
  }
}

function readPendingSources(path: string, userId: number): {
  pending: PendingPackageRequest | null;
  current: PackageRequestStorage;
  legacy: PackageRequestStorage;
  storageKey: string;
} {
  const storageKey = packageWorkflowStorageKey(path, userId);
  const { current, legacy } = requirePackageWorkflowStorage();
  const saved = readPendingFromStorage(current, storageKey);
  const legacySaved = readPendingFromStorage(legacy, storageKey);
  if (saved && legacySaved && (saved.requestKey !== legacySaved.requestKey
    || JSON.stringify(saved.body) !== JSON.stringify(legacySaved.body))) {
    throw new Error("Conflicting package recovery data exists in another browser tab");
  }
  return { pending: saved || legacySaved, current, legacy, storageKey };
}

function packageWorkflowLocks(): LockManager {
  const locks = globalThis.navigator?.locks;
  if (!locks) throw new Error("Safe cross-tab package recovery is unavailable");
  return locks;
}

export function isPackagePrintRun(value: unknown): value is PackagePrintRun {
  if (!value || typeof value !== "object") return false;
  const run = value as Partial<PackagePrintRun>;
  return Number.isInteger(run.id) && Number(run.id) > 0 && typeof run.run_no === "string";
}

export function pendingPackageWorkflow(path: string, userId: number): PendingPackageRequest | null {
  if (typeof window === "undefined") return null;
  return readPendingSources(path, userId).pending;
}

async function preparePendingPackageWorkflow(
  path: string,
  userId: number,
  body: unknown,
): Promise<{ pending: PendingPackageRequest; isNew: boolean }> {
  const storageKey = packageWorkflowStorageKey(path, userId);
  return packageWorkflowLocks().request(storageKey, () => {
    const sources = readPendingSources(path, userId);
    if (sources.pending) {
      if (JSON.stringify(sources.pending.body) !== JSON.stringify(body)) {
        throw new Error("Retry the saved package request before submitting changed values");
      }
      // Migrate old tab-scoped evidence while holding the shared lock. Another
      // tab cannot race this migration with a newly generated request key.
      let migrated = false;
      if (!readPendingFromStorage(sources.current, storageKey)) {
        sources.current.setItem(storageKey, JSON.stringify(sources.pending));
        migrated = true;
      }
      if (readPendingFromStorage(sources.legacy, storageKey)) {
        sources.legacy.removeItem(storageKey);
        migrated = true;
      }
      if (migrated) notifyPackageWorkflowChanged();
      return { pending: sources.pending, isNew: false };
    }
    const pending = { requestKey: crypto.randomUUID(), body: body as Record<string, any> };
    try {
      sources.current.setItem(storageKey, JSON.stringify(pending));
    } catch {
      throw new Error("Package recovery storage is unavailable");
    }
    notifyPackageWorkflowChanged();
    return { pending, isNew: true };
  });
}

async function clearPendingPackageWorkflow(
  path: string,
  userId: number,
  requestKey: string,
): Promise<boolean> {
  const storageKey = packageWorkflowStorageKey(path, userId);
  return packageWorkflowLocks().request(storageKey, () => {
    const sources = readPendingSources(path, userId);
    if (!sources.pending || sources.pending.requestKey !== requestKey) return false;
    try {
      if (readPendingFromStorage(sources.current, storageKey)?.requestKey === requestKey) {
        sources.current.removeItem(storageKey);
      }
      if (readPendingFromStorage(sources.legacy, storageKey)?.requestKey === requestKey) {
        sources.legacy.removeItem(storageKey);
      }
    } catch {
      throw new Error("Package recovery storage is unavailable");
    }
    notifyPackageWorkflowChanged();
    return true;
  });
}

// Preserve BOTH identity and payload through uncertain responses/reload. Edits
// cannot turn a lost response into an accidental second physical-stock receipt.
export async function postPackageWorkflow<T>(path: string, body: unknown, userId: number): Promise<T> {
  if (!userId) throw new Error("Sign in before recording packages");
  const prepared = await preparePendingPackageWorkflow(path, userId, body);
  const { pending } = prepared;
  try {
    const result = await api.post<T>(path, { ...pending.body, request_key: pending.requestKey }, 60_000);
    if (!await clearPendingPackageWorkflow(path, userId, pending.requestKey)) {
      const newer = pendingPackageWorkflow(path, userId);
      if (newer && newer.requestKey !== pending.requestKey) {
        throw new Error("A newer pending package request is active; retry that saved request");
      }
    }
    return result;
  } catch (error: any) {
    const message = String(error?.message);
    // Package workflow routes serialize a request key and check its committed
    // replay before their 400/409 business rules. A retry reaching either rule
    // therefore proves that the saved request did not commit, so corrected
    // values may safely use a new key. Permission, throttling, not-found, gone,
    // and schema-validation responses can happen before replay and stay pending.
    const definitelyRejectedRetry = !prepared.isNew && /^(400|409):/.test(message);
    const definitelyRejectedFirstAttempt = prepared.isNew && /^(400|401|403|404|409|422|429):/.test(message);
    if (definitelyRejectedRetry || definitelyRejectedFirstAttempt) {
      await clearPendingPackageWorkflow(path, userId, pending.requestKey);
    }
    throw error;
  }
}

export type PackageWorkflowReconciliation<T> =
  | { status: "completed"; result: T }
  | { status: "completed_unavailable" }
  | { status: "cancelled" };

const reconciliationPath: Record<string, string> = {
  "/api/packages/manual-receipt": "/api/packages/manual-receipt/reconcile",
  "/api/packages/print-runs": "/api/packages/print-runs/reconcile",
  "/api/packages/print-runs/create-packages": "/api/packages/print-runs/create-packages/reconcile",
  "/api/shipments": "/api/shipments/reconcile",
};

export async function reconcilePendingPackageWorkflow<T>(
  path: string,
  userId: number,
): Promise<PackageWorkflowReconciliation<T>> {
  if (!userId) throw new Error("Sign in before reconciling packages");
  const endpoint = reconciliationPath[path];
  if (!endpoint) throw new Error("This package workflow does not support reconciliation");
  const pending = pendingPackageWorkflow(path, userId);
  if (!pending) throw new Error("No pending package request to reconcile");
  const result = await api.post<PackageWorkflowReconciliation<T>>(
    endpoint,
    { ...pending.body, request_key: pending.requestKey },
    60_000,
  );
  if (!result || !["completed", "completed_unavailable", "cancelled"].includes(result.status)
      || (result.status === "completed" && (!("result" in result) || result.result == null))
      || (result.status === "completed_unavailable" && "result" in result)) {
    throw new Error("Package request reconciliation returned an invalid status");
  }
  if (!await clearPendingPackageWorkflow(path, userId, pending.requestKey)) {
    const newer = pendingPackageWorkflow(path, userId);
    if (newer && newer.requestKey !== pending.requestKey) {
      throw new Error("A newer pending package request is active; retry that saved request");
    }
  }
  return result;
}
